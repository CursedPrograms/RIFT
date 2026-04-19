using UnityEngine;
using System.Net;
using System.Threading;
using System.IO;

public class main : MonoBehaviour
{
    private HttpListener listener;
    private Thread listenerThread;

    void Start()
    {
        // Initialize the listener
        listener = new HttpListener();
        listener.Prefixes.Add("http://localhost:5000/");
        listener.Start();

        // Run the listener on a separate thread so it doesn't freeze the game
        listenerThread = new Thread(HandleRequests);
        listenerThread.Start();

        Debug.Log("Server started at http://localhost:5000/");
    }

    private void HandleRequests()
    {
        while (listener.IsListening)
        {
            var context = listener.GetContext(); // This waits (blocks) for a request
            var request = context.Request;
            var response = context.Response;

            Debug.Log($"Request received: {request.Url}");

            // Create some "Flask-like" response content
            string responseString = "<html><body><h1>Hello from Unity!</h1><p>The game is running.</p></body></html>";
            byte[] buffer = System.Text.Encoding.UTF8.GetBytes(responseString);

            response.ContentLength64 = buffer.Length;
            Stream output = response.OutputStream;
            output.Write(buffer, 0, buffer.Length);
            output.Close();
        }
    }

    private void OnApplicationQuit()
    {
        // Clean up the thread and listener when you stop the game
        if (listener != null)
        {
            listener.Stop();
            listener.Close();
        }

        if (listenerThread != null)
        {
            listenerThread.Abort();
        }
    }
}
