package io.nekohasekai.sfa.obhod

import org.json.JSONObject
import java.io.File

/** DNS must follow the selected working tunnel, including when SS is unavailable. */
object ObhodConfigRepair {
    /** Also apply the repair at start/reload, before the bootstrap coroutine has finished. */
    fun read(file: File): String = synchronized(this) {
        val content = file.readText()
        if (file.name.startsWith("obhod-")) repair(content) ?: content else content
    }

    fun repair(content: String): String? {
        val config = JSONObject(content)
        val outbounds = config.optJSONArray("outbounds") ?: return null
        val transports = (0 until outbounds.length()).map { outbounds.getJSONObject(it) }
        val proxyTags = transports.filter {
            (it.optString("tag") == "hy2" && it.optString("type") == "hysteria2") ||
                (it.optString("tag") == "ss" && it.optString("type") == "shadowsocks")
        }.map { it.getString("tag") }.toSet()
        if (proxyTags.isEmpty()) return null
        val final = config.optJSONObject("route")?.optString("final").orEmpty()
        val automatic = transports.firstOrNull { it.optString("tag") == final && it.optString("type") == "urltest" }
        val candidates = automatic?.optJSONArray("outbounds")
        val validAutomatic = candidates != null && candidates.length() > 0 &&
            (0 until candidates.length()).all { candidates.getString(it) in proxyTags }
        if (final !in proxyTags && !validAutomatic) return null
        val servers = config.optJSONObject("dns")?.optJSONArray("servers") ?: return null
        var changed = false
        for (i in 0 until servers.length()) {
            val server = servers.getJSONObject(i)
            if (server.optString("tag") != "doh" || server.optString("type") != "https") continue
            if (server.optString("detour") !in proxyTags) continue
            if (server.optString("detour") != final) {
                server.put("detour", final)
                changed = true
            }
        }
        return if (changed) config.toString(2) else null
    }
}
