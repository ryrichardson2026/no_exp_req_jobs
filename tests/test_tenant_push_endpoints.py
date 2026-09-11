"""Tenant-push acceptance: config endpoints resolve through the REAL adapter URL
builders to the literal endpoint strings in the directive, and the Workday builder
handles BOTH host styles from the same code. No network. Run: python tests/test_tenant_push_endpoints.py
(the repo has no pytest; plain asserts + exit code)."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from adapters import workday, oracle_orc, successfactors_rmk, adp_wfn  # noqa: E402

TENANTS = json.load(open(os.path.join(ROOT, "config", "tenants.json"), encoding="utf-8"))
fails = []


def check(name, got, want):
    if got != want:
        fails.append(f"{name}\n    got:  {got}\n    want: {want}")


# --- Sysco: Workday 'myworkdaysite' style (tenant in the PATH) ---
sysco = TENANTS["workday"]["sysco"]
careers, cxs = workday.base_urls(sysco)
check("sysco cxs list", cxs + "/jobs",
      "https://wd5.myworkdaysite.com/wday/cxs/sysco/syscocareers/jobs")
check("sysco careers/public", careers,
      "https://wd5.myworkdaysite.com/en-US/recruiting/sysco/syscocareers")
check("sysco config list_url matches builder", sysco["list_url"], cxs + "/jobs")

# --- Acceptance #3: the SAME builder resolves an existing 'myworkdayjobs' tenant ---
uhaul = TENANTS["workday"]["uhaul"]
_, uhaul_cxs = workday.base_urls(uhaul)
check("uhaul (myworkdayjobs) cxs", uhaul_cxs,
      "https://uhaul.wd1.myworkdayjobs.com/wday/cxs/uhaul/UhaulJobs")
assert sysco.get("url_style") == "myworkdaysite" and uhaul.get("url_style") == "myworkdayjobs", \
    "both host styles must be exercised"

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
print("OK: sysco (myworkdaysite) + uhaul (myworkdayjobs) + sherwin endpoints resolve to the literal spec strings")
sys.exit(0)
