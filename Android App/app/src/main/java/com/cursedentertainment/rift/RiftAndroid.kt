// RiftAndroid.kt - the Android-only glue around the hub in NetworkDiscovery.kt:
// APK-asset dashboard files, a Bluetooth RFCOMM link to NORA, a foreground
// service that keeps the hub alive, and the app's screen: a start/stop switch,
// the hub's address, the fleet list and RIFT's own dashboard in a WebView.
//
// The dashboard files (templates/, static/, colour_scheme.xml), the colours and the
// launcher icon all come from RIFT's folders at build time (app/build.gradle.kts).
package com.cursedentertainment.rift

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothSocket
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.content.res.AssetManager
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.text.InputType
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast
import java.io.InputStream
import java.net.Inet4Address
import java.net.NetworkInterface
import java.util.UUID

class AndroidAssets(private val assets: AssetManager) : RiftAssets {
    private fun read(path: String): ByteArray? =
        try { assets.open(path).use(InputStream::readBytes) } catch (_: Exception) { null }

    override fun template(): String? = read("templates/index.html")?.toString(Charsets.UTF_8)
    override fun staticFile(rel: String): ByteArray? = read("static/$rel")
    override fun page(name: String): String? = read("templates/$name")?.toString(Charsets.UTF_8)
    override fun colours(): String? = read("colour_scheme.xml")?.toString(Charsets.UTF_8)
}

/** Bluetooth serial (SPP) to NORA; the "port" in POST /mode is her paired MAC address, e.g. "AA:BB:CC:DD:EE:FF". */
@SuppressLint("MissingPermission")   // BLUETOOTH_CONNECT is asked for when the hub starts; without it this throws and the heartbeat retries
class AndroidBtLink(context: Context, mac: String) : BtLink {
    private val socket: BluetoothSocket
    private val input: InputStream
    private val output: java.io.OutputStream

    init {
        val adapter = (context.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager).adapter
            ?: throw UnsupportedOperationException("no Bluetooth adapter")
        socket = adapter.getRemoteDevice(mac).createRfcommSocketToServiceRecord(UUID.fromString("00001101-0000-1000-8000-00805F9B34FB"))
        adapter.cancelDiscovery()
        socket.connect()
        input = socket.inputStream
        output = socket.outputStream
    }

    override fun register(name: String, capabilities: String): Boolean {
        while (input.available() > 0) input.read()
        output.write("H$name:$capabilities\n".toByteArray())
        output.flush()
        val line = StringBuilder()
        val deadline = System.currentTimeMillis() + 2000
        while (System.currentTimeMillis() < deadline) {
            if (input.available() > 0) {
                val c = input.read()
                if (c == '\n'.code) return line.toString().trim() == "OK"
                line.append(c.toChar())
            } else Thread.sleep(20)
        }
        return false
    }

    override fun close() { try { socket.close() } catch (_: Exception) { } }
}

private fun localIpv4(): String {
    try {
        for (nif in NetworkInterface.getNetworkInterfaces()) {
            if (!nif.isUp || nif.isLoopback) continue
            for (addr in nif.inetAddresses) if (addr is Inet4Address && !addr.isLoopbackAddress) return addr.hostAddress ?: continue
        }
    } catch (_: Exception) { }
    return "127.0.0.1"
}

/** The hub's name and port, kept between runs. */
object RiftPrefs {
    private fun prefs(c: Context) = c.getSharedPreferences("rift", Context.MODE_PRIVATE)
    fun name(c: Context) = prefs(c).getString("name", "RIFT").orEmpty().ifEmpty { "RIFT" }
    fun port(c: Context) = prefs(c).getInt("port", 5000)
    fun save(c: Context, name: String, port: Int) = prefs(c).edit().putString("name", name).putInt("port", port).apply()
}

class RiftService : Service() {
    companion object {
        @Volatile var hub: RiftHub? = null
        @Volatile var lastMessage: String = ""
    }

    private var multicastLock: WifiManager.MulticastLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)
            startForeground(1, buildNotification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        else startForeground(1, buildNotification())
        if (hub != null) return START_STICKY

        // Without the lock most phones' Wi-Fi chips drop multicast packets, so mDNS discovery would hear nothing.
        val wifi = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        multicastLock = wifi.createMulticastLock("rift-mdns").apply { setReferenceCounted(false); acquire() }

        val cfg = RiftConfig(name = RiftPrefs.name(this), port = RiftPrefs.port(this), ip = localIpv4())
        val h = RiftHub(cfg, AndroidAssets(assets), { mac -> AndroidBtLink(applicationContext, mac) }) { lastMessage = it }
        val err = h.start()
        if (err != null) { lastMessage = "Couldn't start the hub: $err"; stopSelf(); return START_NOT_STICKY }
        lastMessage = ""
        hub = h
        return START_STICKY
    }

    private fun buildNotification(): Notification {
        val channelId = "rift"
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(NotificationChannel(channelId, "RIFT hub", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, RiftActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, channelId)
            .setContentTitle("RIFT fleet hub running")
            .setContentText("http://${localIpv4()}:${RiftPrefs.port(this)}")
            .setSmallIcon(R.drawable.ic_stat_rift)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
    }

    override fun onDestroy() {
        hub?.stop()
        hub = null
        multicastLock?.let { if (it.isHeld) it.release() }
        super.onDestroy()
    }
}

/**
 * The app's one screen, built in code: RIFT's avatar and name with the hub's on/off
 * switch, the address robots and browsers use, the fleet list, and RIFT's dashboard
 * (served by the hub on this phone) in a WebView underneath.
 */
class RiftActivity : Activity() {
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var hubSwitch: Switch
    private lateinit var address: TextView
    private lateinit var fleet: TextView
    private lateinit var web: WebView
    private lateinit var placeholder: TextView
    private var shownUrl: String? = null
    private var updating = false        // render() setting the switch mustn't start / stop the hub

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private val refresh = object : Runnable {
        override fun run() {
            render()
            handler.postDelayed(this, 1000)
        }
    }

    private fun render() {
        val h = RiftService.hub
        updating = true
        hubSwitch.isChecked = h != null
        updating = false
        if (h == null) {
            address.text = RiftService.lastMessage.ifEmpty { "Hub stopped. Switch it on to run the fleet from this phone." }
            address.setTextColor(getColor(if (RiftService.lastMessage.isEmpty()) R.color.rift_text_sec else R.color.rift_offline))
            fleet.visibility = View.GONE
            showDashboard(null)
            return
        }
        address.text = "http://${h.cfg.ip}:${h.cfg.port}   (tap to copy)"
        address.setTextColor(getColor(R.color.rift_accent))
        val robots = h.registry.robots()
        val peers = h.peers.snapshot().keys
        fleet.visibility = View.VISIBLE
        fleet.text = buildString {
            append(if (robots.isEmpty()) "No robots yet: they register at the address above." else
                robots.sortedBy { it.name }.joinToString("\n") { "● ${it.name}   ${it.type} @ ${it.ip}" })
            if (peers.isNotEmpty()) append("\nPeers: ").append(peers.joinToString())
        }
        showDashboard("http://127.0.0.1:${h.cfg.port}/")
    }

    private fun showDashboard(url: String?) {
        if (url == shownUrl) return
        shownUrl = url
        web.visibility = if (url == null) View.GONE else View.VISIBLE
        placeholder.visibility = if (url == null) View.VISIBLE else View.GONE
        web.loadUrl(url ?: "about:blank")
    }

    private fun startHub() {
        val wanted = mutableListOf<String>()
        if (Build.VERSION.SDK_INT >= 33) wanted += Manifest.permission.POST_NOTIFICATIONS
        if (Build.VERSION.SDK_INT >= 31) wanted += Manifest.permission.BLUETOOTH_CONNECT   // Bluetooth mode only
        val missing = wanted.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isNotEmpty()) requestPermissions(missing.toTypedArray(), 1)          // the hub starts either way
        RiftService.lastMessage = ""
        startForegroundService(Intent(this, RiftService::class.java))
    }

    private fun stopHub() { stopService(Intent(this, RiftService::class.java)) }

    private fun editSettings() {
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(20), dp(8), dp(20), 0) }
        val name = EditText(this).apply { setText(RiftPrefs.name(context)); hint = "Hub name" }
        val port = EditText(this).apply {
            setText(RiftPrefs.port(context).toString()); hint = "Port"; inputType = InputType.TYPE_CLASS_NUMBER
        }
        box.addView(name)
        box.addView(port)
        AlertDialog.Builder(this).setTitle("Hub settings").setView(box)
            .setPositiveButton("Save") { _, _ ->
                RiftPrefs.save(this, name.text.toString().trim(), port.text.toString().toIntOrNull()?.takeIf { it in 1..65535 } ?: 5000)
                if (RiftService.hub != null) { stopHub(); handler.postDelayed({ startHub() }, 500) }   // restart on the new name / port
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(getColor(R.color.rift_background))
        }
        val top = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14), dp(14), dp(14), dp(8))
        }

        // RIFT's avatar and name, the settings button and the hub switch
        val header = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        val avatar = ImageView(this).apply { setImageResource(R.mipmap.ic_launcher_round) }
        val title = TextView(this).apply {
            text = getString(R.string.app_name)
            setTextColor(getColor(R.color.rift_accent))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 24f)
            typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
            letterSpacing = 0.15f
            setPadding(dp(10), 0, 0, 0)
        }
        val settingsButton = TextView(this).apply {
            text = "⚙"
            setTextColor(getColor(R.color.rift_text_sec))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 22f)
            setPadding(dp(12), dp(4), dp(12), dp(4))
            contentDescription = "Hub settings"
            setOnClickListener { editSettings() }
        }
        hubSwitch = Switch(this).apply {
            text = "Hub  "
            setTextColor(getColor(R.color.rift_text))
            setOnCheckedChangeListener { _, on ->
                if (updating) return@setOnCheckedChangeListener
                if (on) startHub() else stopHub()
                handler.postDelayed({ render() }, 400)
            }
        }
        header.addView(avatar, LinearLayout.LayoutParams(dp(44), dp(44)))
        header.addView(title, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        header.addView(settingsButton)
        header.addView(hubSwitch)

        address = TextView(this).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
            typeface = Typeface.MONOSPACE
            setPadding(0, dp(8), 0, dp(6))
            setOnClickListener {
                val h = RiftService.hub ?: return@setOnClickListener
                val url = "http://${h.cfg.ip}:${h.cfg.port}"
                (getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("RIFT", url))
                Toast.makeText(context, "Copied $url", Toast.LENGTH_SHORT).show()
            }
        }
        fleet = TextView(this).apply {
            setTextColor(getColor(R.color.rift_text))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            setPadding(dp(12), dp(10), dp(12), dp(10))
            maxLines = 6
            background = GradientDrawable().apply {
                setColor(getColor(R.color.rift_panel))
                setStroke(dp(1), getColor(R.color.rift_border))
                cornerRadius = dp(8).toFloat()
            }
        }
        top.addView(header)
        top.addView(address)
        top.addView(fleet)

        web = WebView(this).apply {
            setBackgroundColor(getColor(R.color.rift_background))
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            webViewClient = WebViewClient()      // links (robots' own pages too) open in the app
        }
        placeholder = TextView(this).apply {
            text = "The dashboard shows here while the hub runs."
            setTextColor(getColor(R.color.rift_text_dim))
            gravity = Gravity.CENTER
        }
        root.addView(top)
        root.addView(web, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        root.addView(placeholder, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        setContentView(root)
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (web.visibility == View.VISIBLE && web.canGoBack()) web.goBack()
        else @Suppress("DEPRECATION") super.onBackPressed()
    }

    override fun onResume() { super.onResume(); handler.post(refresh) }
    override fun onPause() { handler.removeCallbacks(refresh); super.onPause() }
}
