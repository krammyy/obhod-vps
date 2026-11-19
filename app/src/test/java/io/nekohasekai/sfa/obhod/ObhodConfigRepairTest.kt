package io.nekohasekai.sfa.obhod

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class ObhodConfigRepairTest {
    private fun profile(final: String = "auto", dns: String = "ss") = JSONObject("""
        {"dns":{"servers":[{"type":"https","tag":"doh","server":"1.1.1.1","detour":"$dns"},{"type":"local","tag":"local"}],"rules":[{"domain_suffix":["example.org"],"server":"local"}]},
         "outbounds":[{"type":"hysteria2","tag":"hy2","server":"203.0.113.5","password":"keep-hy2","tls":{"server_name":"test","insecure":true}},
                      {"type":"shadowsocks","tag":"ss","server":"203.0.113.5","password":"keep-ss"},
                      {"type":"urltest","tag":"auto","outbounds":["hy2","ss"],"url":"https://1.1.1.1/cdn-cgi/trace"}],
         "route":{"final":"$final","rules":[{"ip_is_private":true,"outbound":"direct"}]}}
    """)

    @Test fun dnsFollowsAutoWithoutChangingCredentialsOrRouting() {
        val old = profile()
        val fixed = JSONObject(ObhodConfigRepair.repair(old.toString())!!)
        assertEquals("auto", fixed.getJSONObject("dns").getJSONArray("servers").getJSONObject(0).getString("detour"))
        assertEquals(old.getJSONArray("outbounds").toString(), fixed.getJSONArray("outbounds").toString())
        assertEquals(old.getJSONObject("route").toString(), fixed.getJSONObject("route").toString())
        assertEquals(old.getJSONObject("dns").getJSONArray("rules").toString(), fixed.getJSONObject("dns").getJSONArray("rules").toString())
        assertNull(ObhodConfigRepair.repair(fixed.toString()))
    }

    @Test fun singleTransportAndExplicitSelectionNeverReferToMissingAuto() {
        val hy2 = profile("hy2")
        assertEquals("hy2", JSONObject(ObhodConfigRepair.repair(hy2.toString())!!).getJSONObject("dns").getJSONArray("servers").getJSONObject(0).getString("detour"))
        assertNull(ObhodConfigRepair.repair(profile("ss").toString()))
        assertNull(ObhodConfigRepair.repair(profile("auto", "auto").toString()))
        assertNull(ObhodConfigRepair.repair(profile("direct").toString()))
    }

    @Test fun unrelatedOrIncompleteProfilesAreNotRewritten() {
        assertNull(ObhodConfigRepair.repair("{}"))
        assertNull(ObhodConfigRepair.repair(profile("auto", "custom-dns-tunnel").toString()))
        val missing = profile()
        missing.getJSONArray("outbounds").remove(2)
        assertNull(ObhodConfigRepair.repair(missing.toString()))
        val bad = profile()
        bad.getJSONArray("outbounds").getJSONObject(2).getJSONArray("outbounds").put("missing")
        assertNull(ObhodConfigRepair.repair(bad.toString()))
    }
}
