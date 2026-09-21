// RiftAndroid.kt - the Android-only glue around the hub in NetworkDiscovery.kt:
// APK-asset dashboard files, a Bluetooth RFCOMM link to NORA, a foreground
// service that keeps the hub alive, and a small activity to start/stop it.
//
// Setup: copy the repo's templates/index.html to app/src/main/assets/templates/
// and the static/ folder to app/src/main/assets/static/; add to the manifest
//   <uses-permission android:name="android.permission.INTERNET"/>
//   <uses-permission android:name="android.permission.ACCESS_WIFI_STATE"/>
//   <uses-permission android:name="android.permission.CHANGE_WIFI_MULTICAST_STATE"/>
//   <uses-permission android:name="android.permission.FOREGROUND_SERVICE"/>
//   <uses-permission android:name="android.permission.BLUETOOTH_CONNECT"/>
//   <application android:usesCleartextTraffic="true"> ...
//     <activity android:name=".RiftActivity" android:exported="true"> (MAIN/LAUNCHER)
//     <service android:name=".RiftService" android:foregroundServiceType="dataSync"/>
// and add "org.nanohttpd:nanohttpd:2.3.1" to the Gradle dependencies.
package com.example.riftcontrol

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothSocket
import android.content.Context
import android.content.Intent
import android.content.res.AssetManager
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.text.InputType
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import java.io.InputStream
import java.net.Inet4Address
import java.net.NetworkInterface
import java.util.UUID

class AndroidAssets(private val assets: AssetManager) : RiftAssets {
    private fun read(path: String): ByteArray? =
        try { assets.open(path).use(InputStream::readBytes) } catch (_: Exception) { null }

    override fun template(): String? = read("templates/index.html")?.toString(Charsets.UTF_8)
    override fun staticFile(rel: String): ByteArray? = read("static/$rel")
}

/** Bluetooth serial (SPP) to NORA; the "port" in POST /mode is her paired MAC address, e.g. "AA:BB:CC:DD:EE:FF". */
class AndroidBtLink(mac: String) : BtLink {
    private val socket: BluetoothSocket
    private val input: InputStream
    private val output: java.io.OutputStream

    init {
        val adapter = BluetoothAdapter.getDefaultAdapter() ?: throw UnsupportedOperationException("no Bluetooth adapter")
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

class RiftService : Service() {
    companion object {
        @Volatile var hub: RiftHub? = null
        @Volatile var lastMessage: String = ""
        const val EXTRA_NAME = "name"
        const val EXTRA_PORT = "port"
    }

    private var multicastLock: WifiManager.MulticastLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(1, buildNotification())
        if (hub != null) return START_STICKY

        // Without the lock most phones' Wi-Fi chips drop multicast packets, so mDNS discovery would hear nothing.
        val wifi = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        multicastLock = wifi.createMulticastLock("rift-mdns").apply { setReferenceCounted(false); acquire() }

        val cfg = RiftConfig(
            name = intent?.getStringExtra(EXTRA_NAME).orEmpty().ifEmpty { "RIFT" },
            port = intent?.getIntExtra(EXTRA_PORT, 5000) ?: 5000,
            ip = localIpv4(),
        )
        val h = RiftHub(cfg, AndroidAssets(assets), { mac -> AndroidBtLink(mac) }) { lastMessage = it }
        val err = h.start()
        if (err != null) { lastMessage = "Server error: $err"; stopSelf(); return START_NOT_STICKY }
        hub = h
        return START_STICKY
    }

    private fun buildNotification(): Notification {
        val channelId = "rift"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(NotificationChannel(channelId, "RIFT hub", NotificationManager.IMPORTANCE_LOW))
        }
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) Notification.Builder(this, channelId)
        else @Suppress("DEPRECATION") Notification.Builder(this)
        return builder.setContentTitle("RIFT fleet hub running")
            .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth).build()
    }

    override fun onDestroy() {
        hub?.stop()
        hub = null
        multicastLock?.let { if (it.isHeld) it.release() }
        super.onDestroy()
    }
}

/** Minimal UI built in code (no layout XML needed): name + port, Start/Stop, and a status line. */
class RiftActivity : Activity() {
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var status: TextView

    private val refresh = object : Runnable {
        override fun run() {
            val h = RiftService.hub
            status.text = if (h == null) RiftService.lastMessage.ifEmpty { "Stopped" } else
                "Running - http://${h.cfg.ip}:${h.cfg.port}\n" +
                    "Robots: " + h.registry.robots().joinToString { it.name }.ifEmpty { "(none)" } + "\n" +
                    "Peers: " + h.peers.snapshot().keys.joinToString().ifEmpty { "(none)" }
            handler.postDelayed(this, 1000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val pad = (16 * resources.displayMetrics.density).toInt()
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(pad, pad, pad, pad) }
        val name = EditText(this).apply { setText("RIFT"); hint = "Hub name" }
        val port = EditText(this).apply { setText("5000"); hint = "Port"; inputType = InputType.TYPE_CLASS_NUMBER }
        status = TextView(this)
        val start = Button(this).apply {
            text = "Start hub"
            setOnClickListener {
                val i = Intent(this@RiftActivity, RiftService::class.java)
                    .putExtra(RiftService.EXTRA_NAME, name.text.toString().trim())
                    .putExtra(RiftService.EXTRA_PORT, port.text.toString().toIntOrNull() ?: 5000)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(i) else startService(i)
            }
        }
        val stop = Button(this).apply {
            text = "Stop hub"
            setOnClickListener { stopService(Intent(this@RiftActivity, RiftService::class.java)) }
        }
        for (v in listOf(name, port, start, stop, status))
            root.addView(v, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        setContentView(root)
    }

    override fun onResume() { super.onResume(); handler.post(refresh) }
    override fun onPause() { handler.removeCallbacks(refresh); super.onPause() }
}
