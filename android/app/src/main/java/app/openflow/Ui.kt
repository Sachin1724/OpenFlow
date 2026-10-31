package app.openflow

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
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.windowInsetsPadding
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

/** Apple-dark color palette. Neutral grays, deep blacks, blue accent. */
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

val AkiraExpanded = FontFamily(
    Font(R.font.akira_expanded, FontWeight.Bold)
)

@Composable
fun T(
    s: String,
    size: Int = 16,
    w: FontWeight = FontWeight.Normal,
    c: Color = C.text,
    modifier: Modifier = Modifier,
    max: Int = Int.MAX_VALUE,
    line: Int = 0,
    font: FontFamily = Inter
) = BasicText(
    s,
    modifier,
    style = TextStyle(
        color = c,
        fontSize = size.sp,
        fontWeight = w,
        fontFamily = font,
        lineHeight = if (line > 0) line.sp else TextUnit.Unspecified
    ),
    maxLines = max,
    overflow = TextOverflow.Ellipsis
)

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
    T(title.uppercase(), 22, FontWeight.Bold, font = AkiraExpanded)
    if (sub.isNotEmpty()) T(sub, 14, c = C.text2, modifier = Modifier.padding(top = 6.dp))
}

@Composable
fun SectionLabel(s: String) = T(s.uppercase(), 11, FontWeight.Bold, C.text2, Modifier.padding(start = 20.dp, top = 22.dp, bottom = 8.dp), font = AkiraExpanded)

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
            drawRoundRect(color, Offset(w * 0.2f, w * 0.12f), androidx.compose.ui.geometry.Size(w * 0.6f, w * 0.76f),
                androidx.compose.ui.geometry.CornerRadius(4.dp.toPx()), style = st)
            drawLine(color, Offset(w * 0.35f, w * 0.35f), Offset(w * 0.65f, w * 0.35f), 1.5.dp.toPx(), StrokeCap.Round)
            drawLine(color, Offset(w * 0.35f, w * 0.5f), Offset(w * 0.65f, w * 0.5f), 1.5.dp.toPx(), StrokeCap.Round)
            drawLine(color, Offset(w * 0.35f, w * 0.65f), Offset(w * 0.52f, w * 0.65f), 1.5.dp.toPx(), StrokeCap.Round)
        }
        Ico.Models -> {
            drawRoundRect(color, Offset(w * 0.15f, w * 0.15f), androidx.compose.ui.geometry.Size(w * 0.7f, w * 0.7f),
                androidx.compose.ui.geometry.CornerRadius(6.dp.toPx()), style = st)
            drawLine(color, Offset(w / 2, w * 0.35f), Offset(w / 2, w * 0.65f), 2.dp.toPx(), StrokeCap.Round)
            drawLine(color, Offset(w * 0.35f, w * 0.5f), Offset(w * 0.65f, w * 0.5f), 2.dp.toPx(), StrokeCap.Round)
        }
        Ico.Settings -> {
            drawCircle(color, w * 0.2f, style = st)
            for (i in 0 until 6) {
                val a = i * (Math.PI / 3)
                val p1 = Offset((w / 2 + Math.cos(a) * w * 0.28f).toFloat(), (w / 2 + Math.sin(a) * w * 0.28f).toFloat())
                val p2 = Offset((w / 2 + Math.cos(a) * w * 0.42f).toFloat(), (w / 2 + Math.sin(a) * w * 0.42f).toFloat())
                drawLine(color, p1, p2, 2.dp.toPx(), StrokeCap.Round)
            }
        }
    }
}

/** Bottom navigation bar with 4 tabs. */
@Composable
fun TabBar(selected: Int, onSelect: (Int) -> Unit) {
    Box(Modifier.fillMaxWidth().background(C.bg).windowInsetsPadding(WindowInsets.navigationBars)) {
        Box(Modifier.fillMaxWidth().height(1.dp).background(C.hair))
        Row(Modifier.fillMaxWidth().height(56.dp), horizontalArrangement = Arrangement.SpaceAround, verticalAlignment = Alignment.CenterVertically) {
            listOf("History" to Ico.History, "Notes" to Ico.Notes, "Models" to Ico.Models, "Settings" to Ico.Settings).forEachIndexed { i, (label, ico) ->
                val on = selected == i
                val col = if (on) C.text else C.text3
                Column(Modifier.weight(1f).press { onSelect(i) }, horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(ico, col); T(label, 11, FontWeight.Medium, col, Modifier.padding(top = 3.dp))
                }
            }
        }
    }
}
