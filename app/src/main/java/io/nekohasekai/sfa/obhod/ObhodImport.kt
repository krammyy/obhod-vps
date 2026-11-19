package io.nekohasekai.sfa.obhod

import android.content.Context
import android.util.Base64
import io.nekohasekai.libbox.Libbox
import io.nekohasekai.sfa.database.Profile
import io.nekohasekai.sfa.database.ProfileManager
import io.nekohasekai.sfa.database.Settings
import io.nekohasekai.sfa.database.TypedProfile
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * obhod://add?d=<base64url(json)> links produced by the desktop app (Servers → Phone / QR).
 *
 * The link carries only server credentials; routing comes from assets/obhod/template.json,
 * which the desktop app generates from the same rules as its own Work mode.
 */
object ObhodImport {
    const val PREFIX = "obhod://add?d="
    private val tokenRegex = Regex("^[A-Za-z0-9._~+/=-]{1,256}$")
    private val hostRegex = Regex("^[A-Za-z0-9.:-]{1,253}$")

    data class Server(
        val name: String,
        val host: String,
        val hy2Port: Int?,
        val hy2Password: String?,
        val hy2Obfs: String?,
        val hy2Sni: String,
        val ssPort: Int?,
        val ssPassword: String?,
        val ssMethod: String,
    )

    fun isLink(value: String): Boolean = value.trim().startsWith(PREFIX)

    fun parse(link: String): Server {
        val text = link.trim()
        require(text.startsWith(PREFIX)) { "Это не ссылка OBHOD" }
        val blob = text.removePrefix(PREFIX).substringBefore('&')
        val json =
            try {
                JSONObject(String(Base64.decode(blob, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)))
            } catch (e: Exception) {
                throw IllegalArgumentException("Ссылка OBHOD повреждена: ${e.message}")
            }
        require(json.optInt("v") == 1) { "Неподдерживаемая версия ссылки OBHOD" }
        val host = json.optString("h")
        require(hostRegex.matches(host)) { "Некорректный адрес сервера" }
        val hy2Password = json.optString("hw").ifEmpty { null }
        val ssPassword = json.optString("sw").ifEmpty { null }
        require(hy2Password != null || ssPassword != null) { "В ссылке нет ни одного транспорта" }
        listOfNotNull(hy2Password, ssPassword, json.optString("ho").ifEmpty { null }).forEach {
            require(tokenRegex.matches(it)) { "Недопустимые символы в ключах" }
        }
        return Server(
            name = json.optString("n").ifBlank { host }.take(40),
            host = host,
            hy2Port = if (hy2Password != null) json.optInt("hp", 2080) else null,
            hy2Password = hy2Password,
            hy2Obfs = json.optString("ho").ifEmpty { null },
            hy2Sni = json.optString("hs").ifEmpty { "example.invalid" },
            ssPort = if (ssPassword != null) json.optInt("sp", 8388) else null,
            ssPassword = ssPassword,
            ssMethod = json.optString("sm").ifEmpty { "aes-256-gcm" },
        )
    }

    fun buildConfig(context: Context, server: Server): String {
        val templateText = context.assets.open("obhod/template.json").bufferedReader().use { it.readText() }
        val templateHost = "example.invalid"
        val config = JSONObject(templateText)
        val outbounds = config.getJSONArray("outbounds")
        val kept = JSONArray()
        val tags = mutableListOf<String>()
        for (i in 0 until outbounds.length()) {
            val item = outbounds.getJSONObject(i)
            when (item.optString("tag")) {
                "hy2" -> {
                    if (server.hy2Password == null) continue
                    item.put("server", server.host)
                    item.put("server_port", server.hy2Port)
                    item.put("password", server.hy2Password)
                    item.getJSONObject("tls").put("server_name", server.hy2Sni)
                    if (server.hy2Obfs != null) {
                        item.getJSONObject("obfs").put("password", server.hy2Obfs)
                    } else {
                        item.remove("obfs")
                    }
                    tags.add("hy2")
                }
                "ss" -> {
                    if (server.ssPassword == null) continue
                    item.put("server", server.host)
                    item.put("server_port", server.ssPort)
                    item.put("password", server.ssPassword)
                    item.put("method", server.ssMethod)
                    tags.add("ss")
                }
                "auto" -> continue
            }
            kept.put(item)
        }
        val finalTag =
            if (tags.size > 1) {
                val template = (0 until outbounds.length()).map { outbounds.getJSONObject(it) }.first { it.optString("tag") == "auto" }
                kept.put(kept.length() - 1, template) // urltest before "direct"
                kept.put(JSONObject().put("type", "direct").put("tag", "direct"))
                "auto"
            } else {
                tags.first()
            }
        config.put("outbounds", kept)

        val route = config.getJSONObject("route")
        route.put("final", finalTag)
        val rules = route.getJSONArray("rules")
        for (i in 0 until rules.length()) {
            val rule = rules.getJSONObject(i)
            if (rule.optString("outbound") in setOf("auto", "hy2", "ss")) rule.put("outbound", finalTag)
        }
        config.getJSONObject("dns").getJSONArray("servers").getJSONObject(0)
            .put("detour", finalTag)

        // The server's own address must bypass the tunnel.
        val templateCidr = "$templateHost/32"
        fun swapCidr(array: JSONArray?) {
            if (array == null) return
            for (i in 0 until array.length()) {
                if (array.optString(i) == templateCidr) array.put(i, hostCidr(server.host))
            }
        }
        for (i in 0 until rules.length()) swapCidr(rules.getJSONObject(i).optJSONArray("ip_cidr"))
        val inbounds = config.getJSONArray("inbounds")
        for (i in 0 until inbounds.length()) swapCidr(inbounds.getJSONObject(i).optJSONArray("route_exclude_address"))
        return config.toString(2)
    }

    private fun hostCidr(host: String): String =
        if (host.contains(':')) "$host/128" else "$host/32"

    /** Creates (or refreshes) the profile for the link and selects it. */
    suspend fun import(context: Context, link: String): Profile {
        val server = parse(link)
        require(!server.host.any { it.isLetter() }) {
            "На телефоне поддерживаются серверы с IP-адресом, а не доменом"
        }
        val content = buildConfig(context, server)
        Libbox.checkConfig(content)

        val directory = File(context.filesDir, "configs").also { it.mkdirs() }
        val fileName = "obhod-" + server.host.replace(Regex("[^A-Za-z0-9]"), "_") + ".json"
        val configFile = File(directory, fileName)
        configFile.writeText(content)

        val existing = ProfileManager.list()
        val current = existing.firstOrNull { it.typed.path == configFile.path }
        val profile =
            if (current != null) {
                current.name = server.name
                ProfileManager.update(current)
                current
            } else {
                var name = server.name
                var n = 2
                while (existing.any { it.name == name }) name = "${server.name} (${n++})"
                val typed =
                    TypedProfile().apply {
                        type = TypedProfile.Type.Local
                        path = configFile.path
                    }
                Profile(userOrder = existing.size.toLong(), name = name, icon = null, typed = typed).also {
                    ProfileManager.create(it)
                }
            }
        Settings.selectedProfile = profile.id
        return profile
    }
}
