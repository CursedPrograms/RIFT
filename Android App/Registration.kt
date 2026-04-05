 // Registration.kt
package com.example.riftcontrol

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import okhttp3.*
import org.json.JSONObject
import java.io.IOException

class RegistrationActivity : AppCompatActivity() {

    private val serverUrl = "http://192.168.1.1:5000/register" // Replace with your server IP

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_registration)

        // Example: Register KIDA_v00 robot
        val robotName = "KIDA_v00"
        val robotIP = "192.168.1.50"
        val robotType = "tank"
        val capabilities = listOf("camera", "line_follow")

        registerRobot(robotName, robotIP, robotType, capabilities)
    }

    private fun registerRobot(
        name: String,
        ip: String,
        type: String,
        capabilities: List<String>
    ) {
        val client = OkHttpClient()

        // Create JSON body
        val json = JSONObject().apply {
            put("name", name)
            put("ip", ip)
            put("type", type)
            put("capabilities", capabilities)
        }

        val requestBody = RequestBody.create(
            "application/json; charset=utf-8".toMediaTypeOrNull(),
            json.toString()
        )

        val request = Request.Builder()
            .url(serverUrl)
            .post(requestBody)
            .build()

        // Use coroutine to run network on background thread
        CoroutineScope(Dispatchers.IO).launch {
            client.newCall(request).enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    e.printStackTrace()
                }

                override fun onResponse(call: Call, response: Response) {
                    if (response.isSuccessful) {
                        println("Robot registered successfully!")
                    } else {
                        println("Registration failed: ${response.code}")
                    }
                }
            })
        }
    }
}
