package app.openflow

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Design tokens (android/DESIGN.md): dark, black ground, one blue accent, pill shapes. */
object C {
    val bg = Color(0xFF000000)
    val surface = Color(0xFF1C1C1E)
    val surface2 = Color(0xFF2C2C2E)
    val text = Color(0xFFFFFFFF)
    val text2 = Color(0x99EBEBF5)
    val text3 = Color(0x61EBEBF5)
    val accent = Color(0xFF0A84FF)
    val red = Color(0xFFFF453A)
    val green = Color(0xFF30D158)
    val hair = Color(0x14FFFFFF)
}

val Inter = FontFamily(
    Font(R.font.inter_regular, FontWeight.Normal),
    Font(R.font.inter_medium, FontWeight.Medium),
    Font(R.font.inter_semibold, FontWeight.SemiBold),
)

@Composable
fun T(s: String, size: Int = 16, w: FontWeight = FontWeight.Normal, c: Color = C.text, modifier: Modifier = Modifier, max: Int = Int.MAX_VALUE, line: Int = 0) =
    BasicText(s, modifier, style = TextStyle(color = c, fontSize = size.sp, fontWeight = w, fontFamily = Inter,
        lineHeight = if (line > 0) line.sp else TextUnit.Unspecified), maxLines = max, overflow = TextOverflow.Ellipsis)

/** Press feedback on every tappable thing: it dips slightly while the finger is down. */
fun Modifier.press(onClick: () -> Unit): Modifier = composed {
    val src = remember { MutableInteractionSource() }
    val down by src.collectIsPressedAsState()
    val k by animateFloatAsState(if (down) 0.97f else 1f, tween(100), label = "press")
    graphicsLayer { scaleX = k; scaleY = k }.clickable(interactionSource = src, indication = null, onClick = onClick)
}

@Composable
fun PillButton(label: String, primary: Boolean = true, small: Boolean = false, onClick: () -> Unit) =
    Box(Modifier.heightIn(min = if (small) 36.dp else 48.dp).clip(RoundedCornerShape(50))
        .background(if (primary) C.accent else C.surface2).press(onClick).padding(horizontal = if (small) 16.dp else 22.dp),
        contentAlignment = Alignment.Center) { T(label, if (small) 14 else 16, FontWeight.Medium) }

/** An inset group: rows on one rounded surface, separated by a faint inset line. */
@Composable
fun Group(modifier: Modifier = Modifier, content: @Composable () -> Unit) =
    Column(modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp)).background(C.surface)) { content() }

@Composable
fun Sep() = Box(Modifier.padding(start = 16.dp).fillMaxWidth().height(1.dp).background(C.hair))

@Composable
fun Title(title: String, sub: String) = Column(Modifier.padding(horizontal = 20.dp).padding(top = 20.dp, bottom = 14.dp)) {
    T(title, 32, FontWeight.SemiBold)
    if (sub.isNotEmpty()) T(sub, 15, c = C.text2, modifier = Modifier.padding(top = 4.dp))
}

@Composable
fun SectionLabel(s: String) = T(s, 13, FontWeight.Medium, C.text2, Modifier.padding(start = 20.dp, top = 22.dp, bottom = 8.dp))

private enum class Ico { History, Notes, Models, Settings }

@Composable
private fun Icon(kind: Ico, color: Color) = Canvas(Modifier.size(24.dp)) {
    val w = size.width; val st = Stroke(width = 2.dp.toPx(), cap = StrokeCap.Round)
    when (kind) {
        Ico.History -> {
            drawCircle(color, w * 0.42f, style = st)
            drawLine(color, Offset(w / 2, w * 0.28f), Offset(w / 2, w / 2), 2.dp.toPx(), StrokeCap.Round)
            drawLine(color, Offset(w / 2, w / 2), Offset(w * 0.66f, w * 0.6f), 2.dp.toPx(), StrokeCap.Round)
        }
        Ico.Notes -> {
            drawRoundRect(color, Offset(w * 0.18f, w * 0.08f), Size(w * 0.64f, w * 0.84f), androidx.compose.ui.geometry.CornerRadius(w * 0.12f), style = st)
            for (i in 0..2) drawLine(color, Offset(w * 0.32f, w * (0.34f + i * 0.17f)), Offset(w * 0.68f, w * (0.34f + i * 0.17f)), 2.dp.toPx(), StrokeCap.Round)
        }
        Ico.Models -> for (i in 0..2) drawRoundRect(color, Offset(w * 0.12f, w * (0.14f + i * 0.28f)), Size(w * 0.76f, w * 0.2f),
            androidx.compose.ui.geometry.CornerRadius(w * 0.1f), style = st)
        Ico.Settings -> {
            for (i in 0..1) {
                val y = w * (0.32f + i * 0.36f); val kx = w * (if (i == 0) 0.66f else 0.34f)
                drawLine(color, Offset(w * 0.12f, y), Offset(w * 0.88f, y), 2.dp.toPx(), StrokeCap.Round)
                drawCircle(Color.Black, w * 0.13f, Offset(kx, y)); drawCircle(color, w * 0.13f, Offset(kx, y), style = st)
            }
        }
    }
}

/** Bottom bar: four tabs, accent on the selected one, 56 dp tall (comfortably over the 48 dp touch minimum). */
@Composable
fun TabBar(selected: Int, onSelect: (Int) -> Unit) {
    val items = listOf("History" to Ico.History, "Notes" to Ico.Notes, "Models" to Ico.Models, "Settings" to Ico.Settings)
    Row(Modifier.fillMaxWidth().background(C.surface).height(60.dp), horizontalArrangement = Arrangement.SpaceEvenly, verticalAlignment = Alignment.CenterVertically) {
        items.forEachIndexed { i, (label, ico) ->
            val col by animateColorAsState(if (i == selected) C.accent else C.text3, tween(150), label = "tab")
            Column(Modifier.weight(1f).press { onSelect(i) }.padding(vertical = 6.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Icon(ico, col); T(label, 11, FontWeight.Medium, col, Modifier.padding(top = 3.dp))
            }
        }
    }
}

