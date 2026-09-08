/* JobPosting JSON-LD for a single job page (D2 prerender).

   ONE rule governs every field: markup–page parity. Everything emitted here is also
   rendered visible on the job page, and nothing is estimated. An unknown field is
   omitted — never a null, an empty string, or a placeholder. This is why the function
   mirrors record.js's own money() / verbatim() / cityName() logic rather than inventing
   its own: the string in the markup is the string on the page.

   This module is PURE (no window, no React) so the build-time prerender can import it in
   Node. It is used ONLY on job pages — the prerender never calls it for a browse or
   landing page, which is how a list page is prevented from carrying per-job markup
   (Google names that a specific violation).

   Experience emission (Finding 55), exactly:
     NONE_NEEDED            -> experienceRequirements: "no requirements"
     PREFERRED              -> experienceRequirements: <verbatim clause, "preferred" intact>
     REQUIRED + months      -> OccupationalExperienceRequirements { monthsOfExperience }
     REQUIRED, no months    -> experienceRequirements: <requirement as stated>
     WAIVED                 -> experienceRequirements: <as stated>
     NOT_STATED             -> omitted
   monthsOfExperience appears ONLY in the REQUIRED+months branch — never on PREFERRED,
   which the schema treats as a minimum requirement a preference is not. */

// pay_period -> schema QuantitativeValue unitText
const UNIT = { HOURLY: "HOUR", DAILY: "DAY", WEEKLY: "WEEK", MONTHLY: "MONTH", ANNUAL: "YEAR" };

// employment_type (verbatim, employer-published) -> schema/Google employmentType token.
// Only unambiguous mappings emit; anything else is omitted (absence omits the property).
function employmentType(raw){
  const v = String(raw || "").replace(/[\s_-]+/g, "").toLowerCase();
  if (!v) return null;
  if (v.indexOf("fulltime") === 0) return "FULL_TIME";
  if (v.indexOf("parttime") === 0) return "PART_TIME";
  if (v.indexOf("perdiem") === 0) return "PER_DIEM";
  if (v.indexOf("intern") === 0) return "INTERN";
  if (v.indexOf("temporary") === 0 || v.indexOf("seasonal") === 0) return "TEMPORARY";
  if (v.indexOf("contract") === 0) return "CONTRACTOR";
  return null;
}

// Display city name — mirrors resolve.js cityName(): title-case only an all-caps value,
// otherwise leave mixed case as published. Keeps addressLocality == the page's location line.
function cityDisplay(s){
  const raw = String(s || "").trim().replace(/\s+/g, " ");
  if (!raw || raw !== raw.toUpperCase()) return raw;
  const small = { of: 1, the: 1, and: 1, de: 1, la: 1 };
  return raw.toLowerCase().split(" ").map((w, i) => (i > 0 && small[w]) ? w
    : w.split("-").map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join("-")).join(" ");
}

// The verbatim experience clause the page prints — mirrors record.js verbatim(): the
// evidence clause labelled with the condition, else the first clause. Whitespace-folded.
function verbatimClause(r){
  const clauses = r.evidence_clauses || [];
  const hit = clauses.find((c) => c && c.label === r.experience_condition) || clauses[0];
  return hit && hit.clause ? String(hit.clause).replace(/\s+/g, " ").trim() : null;
}

// Months of experience from a REQUIRED clause: "2 years" -> 24, "6 months" -> 6. Returns
// null when no explicit duration is stated (do not estimate — the caller falls back to Text).
function parseMonths(clause){
  if (!clause) return null;
  const y = /(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\b/i.exec(clause);
  if (y) return Math.round(parseFloat(y[1]) * 12);
  const m = /(\d+)\s*\+?\s*months?\b/i.exec(clause);
  if (m) return parseInt(m[1], 10);
  return null;
}

// baseSalary — only when the employer STATED pay (parity with the page's pay line, which
// renders only when salary_is_stated). value/minValue/maxValue mirror record.js money().
function baseSalary(r){
  if (!r.salary_is_stated) return null;
  const unit = UNIT[r.pay_period];
  if (!unit) return null;                       // no period -> no defensible unitText
  const lo = r.salary_min != null ? Number(r.salary_min) : null;
  const hi = r.salary_max != null ? Number(r.salary_max) : null;
  const qv = { "@type": "QuantitativeValue", unitText: unit };
  if (lo != null && hi != null && lo !== hi) { qv.minValue = lo; qv.maxValue = hi; }
  else { const one = lo != null ? lo : hi; if (one == null) return null; qv.value = one; }
  return { "@type": "MonetaryAmount", currency: "USD", value: qv };
}

function experienceRequirements(r){
  const c = r.experience_condition;
  if (c === "NONE_NEEDED") return "no requirements";           // Google's sentinel value
  if (c === "PREFERRED" || c === "WAIVED") return verbatimClause(r);  // Text, verbatim
  if (c === "REQUIRED") {
    const clause = verbatimClause(r);
    const months = parseMonths(clause);
    if (months != null) return { "@type": "OccupationalExperienceRequirements", monthsOfExperience: months };
    return clause;                                             // Text, as stated
  }
  return null;                                                 // NOT_STATED / unknown -> omit
}

/* Build the JobPosting object from a jobs_detail record + the adapter-declared country
   map (config/source_country.json). Returns null if a Google-required field is missing
   rather than emitting invalid markup. `datePosted` is omitted when the employer stated
   no date (absence omits — we do not fabricate a posting date). */
export function jobPostingLd(r, countryBySource){
  if (!r || !r.title || !(r.description_html || r.description_text)) return null;
  const country = (countryBySource || {})[r.source_id] || null;

  const ld = {
    "@context": "https://schema.org/",
    "@type": "JobPosting",
    title: r.title,                              // exactly as the employer published it
    description: r.description_html || r.description_text,
    hiringOrganization: {
      "@type": "Organization",
      name: String(r.company_name || "").split(" /")[0],   // the name shown on the page
    },
  };

  if (r.posted_at) {
    const d = String(r.posted_at).slice(0, 10);
    if (/^\d{4}-\d{2}-\d{2}$/.test(d)) ld.datePosted = d;
  }

  // jobLocation: needs the adapter-declared country AND at least a city or state, else
  // omitted entirely (addressCountry is mandatory whenever jobLocation is present).
  if (country && (r.city || r.state)) {
    const addr = { "@type": "PostalAddress", addressCountry: country };
    const city = cityDisplay(r.city);
    if (city) addr.addressLocality = city;
    if (r.state) addr.addressRegion = r.state;   // printed exactly as published
    ld.jobLocation = { "@type": "Place", address: addr };
  }

  const sal = baseSalary(r);
  if (sal) ld.baseSalary = sal;

  const et = employmentType(r.employment_type);
  if (et) ld.employmentType = et;

  const exp = experienceRequirements(r);
  if (exp != null) ld.experienceRequirements = exp;

  return ld;
}

// Serialize to a <script type="application/ld+json"> tag. '<' is escaped so the payload
// can never break out of the script element.
export function jobPostingScript(ld){
  if (!ld) return "";
  const json = JSON.stringify(ld, null, 2).replace(/</g, "\\u003c");
  return '<script type="application/ld+json">\n' + json + '\n</script>';
}
