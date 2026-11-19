package io.nekohasekai.sfa.compose.screen.dashboard

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.PowerSettingsNew
import androidx.compose.material.icons.filled.Security
import androidx.compose.material.icons.filled.Work
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.nekohasekai.sfa.R
import io.nekohasekai.sfa.compose.theme.ObhodCyan
import io.nekohasekai.sfa.compose.theme.ObhodMint
import io.nekohasekai.sfa.compose.theme.ObhodViolet
import io.nekohasekai.sfa.constant.Status

@Composable
fun ObhodHeroCard(
    serviceStatus: Status,
    selectedProfileName: String?,
    uplink: String,
    downlink: String,
    onToggle: () -> Unit,
    onSelectProfile: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val isRunning = serviceStatus == Status.Started
    val isTransitioning = serviceStatus == Status.Starting || serviceStatus == Status.Stopping
    val canToggle = selectedProfileName != null && !isTransitioning
    val infiniteTransition = rememberInfiniteTransition(label = "obhodHero")
    val pulse by
        infiniteTransition.animateFloat(
            initialValue = 0.96f,
            targetValue = 1.06f,
            animationSpec =
                infiniteRepeatable(
                    animation = tween(1500, easing = FastOutSlowInEasing),
                    repeatMode = RepeatMode.Reverse,
                ),
            label = "connectionPulse",
        )
    val rotation by
        infiniteTransition.animateFloat(
            initialValue = 0f,
            targetValue = 360f,
            animationSpec = infiniteRepeatable(tween(2600, easing = FastOutSlowInEasing)),
            label = "connectionRing",
        )
    val buttonScale by
        animateFloatAsState(
            targetValue = if (isRunning || isTransitioning) pulse else 1f,
            animationSpec = tween(450),
            label = "powerScale",
        )

    val statusColor =
        when (serviceStatus) {
            Status.Started -> ObhodMint
            Status.Starting, Status.Stopping -> ObhodCyan
            Status.Stopped -> Color.White.copy(alpha = 0.62f)
        }
    val statusTitle =
        when (serviceStatus) {
            Status.Started -> stringResource(R.string.obhod_status_protected)
            Status.Starting -> stringResource(R.string.obhod_status_connecting)
            Status.Stopping -> stringResource(R.string.obhod_status_disconnecting)
            Status.Stopped -> stringResource(R.string.obhod_status_ready)
        }
    val statusHint =
        when (serviceStatus) {
            Status.Started -> stringResource(R.string.obhod_tap_to_disconnect)
            Status.Starting, Status.Stopping -> stringResource(R.string.obhod_please_wait)
            Status.Stopped ->
                if (selectedProfileName == null) {
                    stringResource(R.string.obhod_choose_server)
                } else {
                    stringResource(R.string.obhod_tap_to_connect)
                }
        }

    Box(
        modifier =
            modifier
                .fillMaxWidth()
                .shadow(22.dp, RoundedCornerShape(32.dp), ambientColor = ObhodViolet.copy(alpha = 0.25f))
                .clip(RoundedCornerShape(32.dp))
                .background(
                    Brush.linearGradient(
                        colors = listOf(Color(0xFF111B38), Color(0xFF132B4F), Color(0xFF292053)),
                        start = Offset.Zero,
                        end = Offset(1200f, 1200f),
                    ),
                ),
    ) {
        Canvas(Modifier.fillMaxSize()) {
            drawCircle(
                color = ObhodCyan.copy(alpha = 0.10f),
                radius = size.minDimension * 0.58f,
                center = Offset(size.width * 0.94f, size.height * 0.10f),
            )
            drawCircle(
                color = ObhodViolet.copy(alpha = 0.12f),
                radius = size.minDimension * 0.42f,
                center = Offset(size.width * 0.05f, size.height * 0.92f),
            )
        }

        Column(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 22.dp, vertical = 20.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            imageVector = Icons.Default.Security,
                            contentDescription = null,
                            tint = ObhodCyan,
                            modifier = Modifier.size(24.dp),
                        )
                        Spacer(Modifier.width(9.dp))
                        Text(
                            text = "OBHOD",
                            color = Color.White,
                            fontWeight = FontWeight.Black,
                            fontSize = 22.sp,
                            letterSpacing = 1.4.sp,
                        )
                    }
                    Spacer(Modifier.height(2.dp))
                    Text(
                        text = stringResource(R.string.obhod_tagline),
                        color = Color.White.copy(alpha = 0.64f),
                        style = MaterialTheme.typography.bodySmall,
                    )
                }

                Surface(
                    shape = RoundedCornerShape(50),
                    color = statusColor.copy(alpha = 0.14f),
                    border = BorderStroke(1.dp, statusColor.copy(alpha = 0.36f)),
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 11.dp, vertical = 7.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(Modifier.size(7.dp).background(statusColor, CircleShape))
                        Spacer(Modifier.width(7.dp))
                        Text(
                            text = if (isRunning) "ONLINE" else "VPN",
                            color = statusColor,
                            style = MaterialTheme.typography.labelSmall,
                            fontWeight = FontWeight.Bold,
                            letterSpacing = 0.8.sp,
                        )
                    }
                }
            }

            Spacer(Modifier.height(18.dp))

            Box(contentAlignment = Alignment.Center) {
                if (isRunning || isTransitioning) {
                    Canvas(modifier = Modifier.size(124.dp).rotate(rotation)) {
                        drawArc(
                            brush = Brush.sweepGradient(listOf(Color.Transparent, ObhodCyan, ObhodViolet)),
                            startAngle = 12f,
                            sweepAngle = 290f,
                            useCenter = false,
                            style = Stroke(width = 3.dp.toPx(), cap = StrokeCap.Round),
                        )
                    }
                }
                Surface(
                    onClick = onToggle,
                    enabled = canToggle,
                    modifier =
                        Modifier
                            .size(100.dp)
                            .graphicsLayer {
                                scaleX = buttonScale
                                scaleY = buttonScale
                            }
                            .border(1.dp, Color.White.copy(alpha = 0.18f), CircleShape),
                    shape = CircleShape,
                    color =
                        if (isRunning) {
                            ObhodMint.copy(alpha = 0.19f)
                        } else {
                            Color.White.copy(alpha = if (canToggle) 0.12f else 0.06f)
                        },
                    shadowElevation = if (isRunning) 16.dp else 7.dp,
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Icon(
                            imageVector = Icons.Default.PowerSettingsNew,
                            contentDescription = statusHint,
                            tint = if (canToggle || isRunning) Color.White else Color.White.copy(alpha = 0.35f),
                            modifier = Modifier.size(43.dp),
                        )
                    }
                }
            }

            Spacer(Modifier.height(13.dp))

            Crossfade(targetState = serviceStatus, animationSpec = tween(380), label = "statusText") {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(
                        text = statusTitle,
                        color = Color.White,
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        text = statusHint,
                        color = Color.White.copy(alpha = 0.58f),
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }

            Spacer(Modifier.height(16.dp))

            Surface(
                onClick = onSelectProfile,
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
                color = Color.White.copy(alpha = 0.08f),
                border = BorderStroke(1.dp, Color.White.copy(alpha = 0.10f)),
            ) {
                Row(
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(
                        imageVector =
                            if (selectedProfileName?.contains("личный", ignoreCase = true) == true) {
                                Icons.Default.Person
                            } else {
                                Icons.Default.Work
                            },
                        contentDescription = null,
                        tint = ObhodCyan,
                        modifier = Modifier.size(21.dp),
                    )
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Text(
                            text = stringResource(R.string.obhod_active_route),
                            color = Color.White.copy(alpha = 0.52f),
                            style = MaterialTheme.typography.labelSmall,
                        )
                        Text(
                            text = selectedProfileName ?: stringResource(R.string.obhod_choose_server),
                            color = Color.White,
                            style = MaterialTheme.typography.titleSmall,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                    Text(
                        text = stringResource(R.string.obhod_change),
                        color = ObhodCyan,
                        style = MaterialTheme.typography.labelMedium,
                        fontWeight = FontWeight.Bold,
                    )
                }
            }

            AnimatedVisibility(
                visible = isRunning,
                enter = fadeIn(tween(450)),
                exit = fadeOut(tween(220)),
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    TrafficPill(
                        icon = Icons.Default.ArrowDownward,
                        label = stringResource(R.string.download),
                        value = downlink,
                        tint = ObhodMint,
                        modifier = Modifier.weight(1f),
                    )
                    TrafficPill(
                        icon = Icons.Default.ArrowUpward,
                        label = stringResource(R.string.upload),
                        value = uplink,
                        tint = ObhodViolet,
                        modifier = Modifier.weight(1f),
                    )
                }
            }
        }
    }
}

@Composable
private fun TrafficPill(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    value: String,
    tint: Color,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier =
            modifier
                .clip(RoundedCornerShape(15.dp))
                .background(Color.White.copy(alpha = 0.07f))
                .padding(horizontal = 12.dp, vertical = 9.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(8.dp))
        Column {
            Text(text = label, color = Color.White.copy(alpha = 0.46f), style = MaterialTheme.typography.labelSmall)
            Text(text = value, color = Color.White, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold)
        }
    }
}
