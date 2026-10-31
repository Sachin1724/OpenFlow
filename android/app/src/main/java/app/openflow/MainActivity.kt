package app.openflow

import android.graphics.Color
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge

/** Hosts the app screens (History, Notes, Models, Settings). The state lives in [AppState]; Compose redraws from it. */
class MainActivity : ComponentActivity() {
    private lateinit var state: AppState

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        enableEdgeToEdge(statusBarStyle = SystemBarStyle.dark(Color.TRANSPARENT), navigationBarStyle = SystemBarStyle.dark(Color.TRANSPARENT))
        state = AppState(this)
        setContent { App(state) }
    }

    override fun onResume() { super.onResume(); state.refresh() }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<String>, grantResults: IntArray) { super.onRequestPermissionsResult(requestCode, permissions, grantResults); state.refresh() }
}
