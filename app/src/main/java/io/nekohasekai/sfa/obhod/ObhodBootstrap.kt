package io.nekohasekai.sfa.obhod

import android.content.Context
import android.util.AtomicFile
import android.util.Log
import io.nekohasekai.libbox.Libbox
import io.nekohasekai.sfa.database.Profile
import io.nekohasekai.sfa.database.ProfileManager
import io.nekohasekai.sfa.database.Settings
import io.nekohasekai.sfa.database.TypedProfile
import java.io.File

/** Installs and updates the bundled OBHOD server; more servers come from obhod:// links. */
object ObhodBootstrap {
    private const val ASSET_VERSION = 8
    private const val PREFS_NAME = "obhod_bootstrap"
    private const val PREFS_VERSION = "asset_version"

    private data class BundledProfile(
        val asset: String,
        val name: String,
        val fileName: String,
    )

    private val bundledProfiles =
        listOf(
            BundledProfile("obhod/server-default.json", "FastVPS", "obhod-server-default.json"),
        )

    // Servers removed from the client in 2.5.0 (dead or decommissioned).
    private val legacyProfileNames =
        setOf(
            "OBHOD · Работа",
            "OBHOD · Дом",
            "OBHOD · Приватность",
            "Сервер работа",
            "Сервер личный",
        )

    private val legacyConfigFiles =
        listOf(
            "obhod-work.json",
            "obhod-home.json",
            "obhod-privacy.json",
            "obhod-server-work.json",
            "obhod-server-personal.json",
        )

    private val legacyTelegramBypassPackages =
        setOf(
            "org.telegram.messenger",
            "org.telegram.messenger.web",
            "org.telegram.messenger.beta",
            "org.thunderdog.challegram",
        )

    suspend fun installProfiles(context: Context) {
        repairLegacyTelegramBypass()

        val preferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val installedAssetVersion = preferences.getInt(PREFS_VERSION, 0)
        var existing = ProfileManager.list()
        // Repair existing imported and bundled profiles, not only profiles created by this APK.
        val configDirectory = File(context.filesDir, "configs").also { it.mkdirs() }
        for (profile in existing) {
            if (profile.typed.type != TypedProfile.Type.Local) continue
            val file = File(profile.typed.path)
            if (file.parentFile?.canonicalFile != configDirectory.canonicalFile || !file.name.startsWith("obhod-")) continue
            if (!file.isFile) continue
            // A malformed user-edited profile must not abort initialization of all profiles.
            runCatching {
                synchronized(ObhodConfigRepair) {
                    val content = ObhodConfigRepair.repair(file.readText()) ?: return@synchronized
                    Libbox.checkConfig(content)
                    val atomic = AtomicFile(file)
                    val stream = atomic.startWrite()
                    try {
                        stream.write(content.toByteArray(Charsets.UTF_8))
                        atomic.finishWrite(stream)
                    } catch (e: Exception) {
                        atomic.failWrite(stream)
                        throw e
                    }
                }
            }.onFailure {
                Log.w("OBHOD", "Skipped configuration repair for profile ${profile.id}")
            }
        }
        if (installedAssetVersion >= ASSET_VERSION) return

        var selectFirstProfile = Settings.selectedProfile == -1L
        val legacyProfiles = existing.filter { it.name in legacyProfileNames }
        if (legacyProfiles.any { it.id == Settings.selectedProfile }) {
            selectFirstProfile = true
        }
        if (legacyProfiles.isNotEmpty()) {
            ProfileManager.delete(legacyProfiles)
            existing = existing.filterNot { it.name in legacyProfileNames }
        }

        // Config files of the removed servers still hold their credentials.
        legacyConfigFiles.forEach { File(configDirectory, it).delete() }
        var firstProfileId = -1L

        for ((index, item) in bundledProfiles.withIndex()) {
            val content = context.assets.open(item.asset).bufferedReader().use { it.readText() }
            Libbox.checkConfig(content)

            val configFile = File(configDirectory, item.fileName)
            configFile.writeText(content)

            val current = existing.firstOrNull { it.name == item.name }
            if (current != null) {
                current.typed.path = configFile.path
                current.userOrder = index.toLong()
                ProfileManager.update(current)
                if (index == 0) firstProfileId = current.id
                continue
            }

            val typed =
                TypedProfile().apply {
                    type = TypedProfile.Type.Local
                    path = configFile.path
                }
            val created =
                Profile(
                    userOrder = index.toLong(),
                    name = item.name,
                    icon = null,
                    typed = typed,
                )
            ProfileManager.create(created)
            if (index == 0) firstProfileId = created.id
        }

        if (selectFirstProfile && firstProfileId != -1L) {
            Settings.selectedProfile = firstProfileId
        }
        Settings.checkUpdateEnabled = false
        Settings.updateCheckPrompted = true
        preferences.edit().putInt(PREFS_VERSION, ASSET_VERSION).apply()
    }

    /** Removes the bypass added by older OBHOD builds so Telegram is carried by the VPN. */
    private fun repairLegacyTelegramBypass() {
        val cleanedList = Settings.perAppProxyList - legacyTelegramBypassPackages
        Settings.perAppProxyList = cleanedList
        if (
            Settings.perAppProxyMode == Settings.PER_APP_PROXY_EXCLUDE &&
            cleanedList.isEmpty()
        ) {
            Settings.perAppProxyEnabled = false
        }
    }
}
