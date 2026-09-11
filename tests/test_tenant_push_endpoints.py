"""Tenant-push acceptance: config endpoints resolve through the REAL adapter URL
builders to the literal endpoint strings in the directive, and the Workday builder
handles BOTH host styles from the same code. No network. Run: python tests/test_tenant_push_endpoints.py
(the repo has no pytest; plain asserts + exit code)."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from adapters import workday, oracle_orc, successfactors_rmk, adp_wfn, radancy_tb  # noqa: E402

TENANTS = json.load(open(os.path.join(ROOT, "config", "tenants.json"), encoding="utf-8"))
fails = []


def check(name, got, want):
    if got != want:
        fails.append(f"{name}\n    got:  {got}\n    want: {want}")


# --- Sysco: Workday 'myworkdaysite' style (tenant in the PATH) ---
# --- Acceptance #3: the Workday URL builder handles BOTH host styles from ONE code path.
# Under Sysco Path B, Sysco is a radancy_tb tenant (asserted below), so the 'myworkdaysite'
# style is exercised with a synthetic config; the live 'myworkdayjobs' style is U-Haul.
uhaul = TENANTS["workday"]["uhaul"]
_, uhaul_cxs = workday.base_urls(uhaul)
check("uhaul (myworkdayjobs) cxs", uhaul_cxs,
      "https://uhaul.wd1.myworkdayjobs.com/wday/cxs/uhaul/UhaulJobs")
mws = {"url_style": "myworkdaysite", "host": "wd5.myworkdaysite.com",
       "tenant": "sysco", "site": "syscocareers", "language": "en-US"}
mws_careers, mws_cxs = workday.base_urls(mws)
check("myworkdaysite cxs (same builder)", mws_cxs + "/jobs",
      "https://wd5.myworkdaysite.com/wday/cxs/sysco/syscocareers/jobs")
check("myworkdaysite careers (same builder)", mws_careers,
      "https://wd5.myworkdaysite.com/en-US/recruiting/sysco/syscocareers")
assert uhaul.get("url_style") == "myworkdayjobs" and mws["url_style"] == "myworkdaysite", \
    "both Workday host styles must be exercised from the same base_urls()"

# --- Sysco (Path B): a radancy_tb tenant now; its WA-scoped Radancy index + &p=N resolve ---
sysco = radancy_tb.load_tenant("sysco")
check("sysco radancy page1 = index_url", radancy_tb.page_url(sysco, 1), sysco["index_url"])
check("sysco radancy page2 uses &p", radancy_tb.page_url(sysco, 2), sysco["index_url"] + "&p=2")
assert "careers.sysco.com/en/search-jobs/Washington" in sysco["index_url"], \
    "sysco index_url must be the WA-scoped Radancy search path"

# --- Sherwin-Williams: oracle_orc list/detail = host + the adapter's REST paths ---
sw = TENANTS["oracle_orc"]["sherwin_williams"]
check("sherwin list", f"https://{sw['host']}{oracle_orc.LIST_PATH}",
      "https://ejhp.fa.us6.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions")
check("sherwin detail", f"https://{sw['host']}{oracle_orc.DETAIL_PATH}",
      "https://ejhp.fa.us6.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails")
# The employer name is carried in config, never derived from the opaque pod host.
check("sherwin company_name in config", sw.get("company_name"), "Sherwin-Williams")

# --- Cintas: successfactors_rmk search endpoint resolves through the builder ---
cintas = successfactors_rmk.load_tenant("cintas")
cintas_search = successfactors_rmk.search_url(cintas, 0)
check("cintas search endpoint base", cintas_search.split("?")[0],
      "https://careers.cintas.com/search/")
check("cintas apply pattern", cintas["endpoints"]["apply_pattern"].format(posting_id="1421663700"),
      "https://careers.cintas.com/talentcommunity/apply/1421663700/?locale=en_US")
assert "startrow=0" in cintas_search, "startrow cursor must be in the search URL"

# --- Gensco: adp_wfn list endpoint resolves through the builder ---
gensco = adp_wfn.load_tenant("gensco")
gensco_list = adp_wfn.list_url(gensco, 0)
check("gensco list endpoint base", gensco_list.split("?")[0],
      "https://my.adp.com/myadp_prefix/mycareer/public/staffing/v1/job-requisitions/search-custom-filters")
check("gensco listing_page", gensco["endpoints"]["listing_page"],
      "https://myjobs.adp.com/genscocareers/cx/job-listing")

if fails:
    print("FAIL:")
    for f in fails:
        print("  " + f)
    sys.exit(1)
print("OK: workday both host styles (uhaul myworkdayjobs + synthetic myworkdaysite), sysco radancy &p pagination, sherwin/cintas/gensco endpoints all resolve to spec")
sys.exit(0)
