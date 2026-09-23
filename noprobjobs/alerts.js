/* Alert-signup landing pages — one job-type × market page each (WA Retail, WA Food Service, …).
   Destination for social / groups / ads; message-matched to the job type; goal is alert signups.

   ONE component, many pages: every text value lives in the PAGES map below (keyed by the category
   slug in the URL). boot() picks the entry from the path; adding a page = a PAGES key + a build.mjs
   ALERTS row. The design/structure is shared, so a style fix hits every page at once.
   Live data (count, max stated pay, 6 recent jobs, top employers, other-category counts) is baked
   inline by prerender/build.mjs into a <script id="__npj_data"> blob and read in boot() — no client
   query, same pattern as the landing / WA lander. Never commit the generated blob.

   Reuses the landing components + styles wholesale: Header, JobCard, Pressable, the value-prop
   and footer patterns, and styles.css. The hero's search bar is replaced by the signup form.

   Copy rules (spec): never "no resume" / "one-click apply" / "entry level"; always spell out
   "No experience needed". Signups carry NO Make changes: the page identity + channel ride in the
   existing `source` field ("alerts_wa_retail" or "alerts_wa_retail|<channel>"); market/category/UTMs
   are recorded via the GA4 event only. */
import { h, s, raw } from "./ui/h.js";
import { Header } from "./ui/header.js";
import { JobCard } from "./ui/jobCard.js";
import { Pressable } from "./ui/pressable.js";
import { catIconSvg } from "./ui/catIcons.js";
import { track, sourcePage } from "./ui/track.js";
import * as R from "./data/record.js";
import * as L from "./data/resolve.js";
import * as SB from "./data/supabase.js";
import * as RT from "./data/routes.js";
import { marketIndexPath, marketBySlug } from "./data/alertPages.js";

const React = window.React;
const BP = "(min-width:768px)";
const PRODUCT = "NoProbJobs.com";
// Content column. A signup/read page reads far better as a centered column than stretched across
// the full board rail (1120px) — this is what a 1920px desktop was sprawling into. The form is
// constrained narrower still (FORM_MAX). On a phone both collapse to full width.
const RAIL = "760px";
// Vertical rhythm. The .landing-scope tokens (--gap-section:12px, --gap-block:8px) are tuned tight
// for the compact landing and read as one text body on a content page — so this page sets its own
// standard spacing: generous between sections, clear between the info subsections.
const GAP_SECTION = "42px";   // between top-level sections
const GAP_SUB = "28px";       // between the info block's subsections
const GAP_BLOCK = "15px";     // header -> content within a section

// ────────────────────────────────────────────────────────────────────────────
// PAGES — one entry per alert page, keyed by the category slug in the URL
// (/alerts/{market}/{category}/). To add a page: add a key here + a row in build.mjs ALERTS.
// `CONTENT` is set to the right entry at boot() from the path. Every text value lives here.
// ────────────────────────────────────────────────────────────────────────────
// Shared across every page (identical copy) — referenced below to keep the pages readable.
const VALUE_PROPS = [
  ["100% free", "Always free for job seekers."],
  ["No sign-up needed to apply", "Apply directly with the employer."],
  ["Real employers, real jobs", "Every job comes from the company’s own careers page."],
  ["Requirements up front", "Spend less time searching and more time applying."],
  ["Pay transparency", "Shown when the employer states it. Never estimated."],
];
const PAY_WHY = "Washington law requires employers with 15 or more employees to post a wage range and a description of benefits on every job posting. On NoProbJobs, pay is shown only when the employer states it — never estimated.";

const PAGES = {

  retail: {
  // ── identity (must match a data/record.js CATEGORIES value + a launched market) ──
  market: "WA",
  marketName: "Washington",
  marketSlug: "washington",
  category: "Retail",
  categoryName: "Retail",
  categoryNoun: "retail",
  listingPath: "/washington/retail/",

  // ── meta ──
  metaTitle: "Retail Jobs, No Experience Needed | Washington | NoProbJobs",
  metaDescription: "Retail jobs in Washington hiring now, no experience required. Free alerts, apply direct with the employer.",

  // ── hero ──
  h1: "Get Retail Job Alerts",
  heroSub: "Be first to know when new No Experience Required Retail Jobs show up in your area.",
  formButton: "Get free alerts",
  // Cadence microcopy. The automated send is a parallel phase-2 build, so no schedule is promised:
  // "as they’re posted" -> "New jobs as they’re posted. Unsubscribe anytime."
  // Switch to "weekly"/"daily" once the Make → MailerLite flow enforces one.
  cadence: "as they’re posted",

  // ── Why NoProbJobs (value props) ──
  valueProps: [
    ["100% free", "Always free for job seekers."],
    ["No sign-up needed to apply", "Apply directly with the employer."],
    ["Real employers, real jobs", "Every job comes from the company’s own careers page."],
    ["Requirements up front", "Spend less time searching and more time applying."],
    ["Pay transparency", "Shown when the employer states it. Never estimated."],
  ],
  secondSignupHeading: "Get new retail jobs before they fill.",

  // ── "Retail with no experience in Washington" ──
  info: {
    heading: "The Retail Job Market in Washington State",

    whatTheWork: "Retail jobs put you on a store floor: helping customers, running a register, stocking shelves, keeping the store in order, and processing returns or online pickup orders. Most stores train you on the job. You need to be reliable, friendly with customers, and available for the shifts they need.",

    credential: null,

    payHeading: "What retail pays in Washington",
    payIntro: "Washington has the highest statewide minimum wage in the country, so retail pay here starts higher than almost anywhere else.",
    payTable: [
      ["Washington minimum wage (2026)", "$17.13/hr statewide", "2027 rate announced Sep 30, 2026"],
      ["Seattle minimum wage (2026)", "$21.30/hr", null],
      ["Cities above the state rate", "Tukwila, SeaTac, Renton, Burien, Everett, Bellingham, and unincorporated King County", null],
      ["Retail salespersons, Washington", "Typically $22/hr; half earn $18–$24/hr", null],
      ["Cashiers, Washington", "Average $22/hr; half earn $17–$23/hr", null],
      ["Retail supervisors, Washington", "Typically $30/hr; half earn $20–$33/hr", null],
    ],
    payPartTime: "Most retail workers in Washington are part-time: about 85% of retail salespersons worked part-time in the past year.",
    payWhy: "Washington law requires employers with 15 or more employees to post a wage range and a description of benefits on every job posting. On NoProbJobs, pay is shown only when the employer states it — never estimated.",

    whosHiringHeading: "Who’s hiring",
    whosHiringFallback: "Retail hiring in Washington comes from national chains, discount stores and specialty shops. See every current opening on the retail board.",
    seasonalNote: "Retailers commonly add seasonal staff ahead of the holidays, and seasonal roles are some of the easiest retail jobs to get with no experience.",

    stepsHeading: "How hiring usually works",
    stepsIntro: "Every store is different, but most retail hiring follows the same few steps:",
    steps: [
      ["Apply online.", "You’ll enter your contact info and your availability. Availability matters a lot in retail hiring, so be accurate and as open as you can."],
      ["Short assessment (sometimes).", "Some large retailers ask situational questions about customer service and teamwork."],
      ["Recorded video interview (sometimes).", "Some large chains send a link to record answers to a few questions on your phone."],
      ["Interview with a manager.", "Often short and in person. Expect questions like “Tell me about a time you helped someone” or “What does good customer service mean to you?” School, volunteer or life examples count."],
      ["Background check, then start.", "For hourly store roles, the whole process often takes one to two weeks."],
    ],

    tipsHeading: "How to land a retail job with no experience",
    tips: [
      ["Lead with availability.", "Evenings, weekends and holidays are the shifts stores most need to fill."],
      ["Apply to several stores at once.", "Retail hires fast and often. Don’t wait on one application."],
      ["Answer with real examples.", "Helping a neighbor, a school project, a volunteer shift. Managers want to see you’re reliable and good with people."],
      ["Show up like it’s the job.", "On time, phone away, ready to talk about when you can work."],
      ["Follow up.", "If you haven’t heard back in a few days, a short call or visit to the store is normal in retail."],
      ["Consider seasonal roles.", "They’re easier to get, and stores often keep strong seasonal workers."],
    ],

    leadsHeading: "Where retail can lead",
    leadsIntro: "Many retail workers move up within the store:",
    leadsPaths: [["Sales associate / cashier", "Shift lead or key holder (opens and closes the store, runs a shift)", "Supervisor or department lead (typically $30/hr in Washington)", "Assistant store manager / store manager"]],
    leadsNote: "Retail experience also carries over to customer service roles, which in Washington typically pay around $28/hr.",
  },

  // ── FAQ (emitted as FAQPage JSON-LD) ──
  faqHeading: "Getting Hired in Retail FAQ",
  faq: [
    ["Do I need experience to get a retail job in Washington?", "No. Most first-time retail roles — sales associate, cashier and stocker — train you on the job. Every job on this page is marked as not requiring experience."],
    ["How much do retail jobs pay in Washington?", "At least $17.13 an hour statewide in 2026, and more in cities with higher minimums, like Seattle at $21.30. Retail salespersons in Washington typically earn about $22 an hour."],
    ["Are most retail jobs part-time?", "Many are. About 85% of retail salespersons in Washington worked part-time in the past year. Full-time roles are available and are labeled on each job."],
    ["Will I need a resume?", "Many employers ask for one in their application. You don’t need one to browse or get alerts on NoProbJobs."],
    ["How fast can I get hired?", "For hourly store roles, often within one to two weeks from applying. Seasonal hiring can move faster."],
  ],
  },

  "food-services": {
  market: "WA",
  marketName: "Washington",
  marketSlug: "washington",
  category: "Food Services",
  categoryName: "Food Service",
  categoryNoun: "food service",
  listingPath: "/washington/food-services/",

  metaTitle: "Food Service Jobs, No Experience Needed | Washington | NoProbJobs",
  metaDescription: "Food service jobs in Washington hiring now, no experience required. Free alerts, apply direct with the employer.",

  h1: "Get Food Service Job Alerts",
  heroSub: "Be first to know when new No Experience Required Food Service Jobs show up in your area.",
  formButton: "Get free alerts",
  cadence: "as they’re posted",

  valueProps: [
    ["100% free", "Always free for job seekers."],
    ["No sign-up needed to apply", "Apply directly with the employer."],
    ["Real employers, real jobs", "Every job comes from the company’s own careers page."],
    ["Requirements up front", "Spend less time searching and more time applying."],
    ["Pay transparency", "Shown when the employer states it. Never estimated."],
  ],
  secondSignupHeading: "Get new food service jobs before they fill.",

  info: {
    heading: "The Food Service Job Market in Washington State",

    whatTheWork: "Food service covers the counter, the kitchen and the dining room: taking orders, running a register, prepping ingredients, washing dishes, cooking simple menu items, and keeping everything clean. Jobs are in restaurants, fast food, coffee shops, and the cafeterias that serve hospitals, schools, campuses and offices. Most places train you on the job, usually over a few weeks, and no formal education is required.",

    credential: {
      heading: "The Food Worker Card",
      parts: [
        ["para", "Washington requires every food worker to get a Washington State Food Worker Card within 14 days of starting work. You don’t need it to apply."],
        ["bullets", [
          ["Cost:", "$10, set by state rule and the same everywhere in Washington."],
          ["Where:", "online at foodworkercard.wa.gov, or through your local health department."],
          ["How:", "a short food safety course and test."],
          ["How long it lasts:", "your first card is good for 2 years. Renew before it expires and the next card lasts 3 years (5 with approved extra food safety training)."],
          ["Where it works:", "any Washington county. Cards from other states are not accepted."],
        ]],
        ["callout", "Serving alcohol?", "If the job involves serving alcohol, Washington also requires a MAST permit. Servers 18 to 20 get a Class 13 permit (serve beer and wine at tables). Bartending and mixing drinks takes a Class 12 permit, which is 21 and older. Your employer will tell you if you need one."],
      ],
    },

    payHeading: "What food service pays in Washington",
    payIntro: "Washington does not let employers count tips toward minimum wage. You earn at least the full minimum wage, and tips are on top.",
    payTable: [
      ["Washington minimum wage (2026)", "$17.13/hr statewide", "2027 rate announced Sep 30, 2026"],
      ["Seattle minimum wage (2026)", "$21.30/hr", null],
      ["Fast food and counter workers", "Typically $20/hr; half earn $17–$23/hr", null],
      ["Dishwashers", "Typically $22/hr; half earn $18–$24/hr", null],
      ["Food preparation workers", "Typically $23/hr; half earn $19–$25/hr", null],
      ["Cooks, restaurant", "Typically $25/hr; half earn $21–$28/hr", null],
      ["Cooks, cafeteria and institution", "Typically $26/hr; half earn $21–$29/hr", null],
    ],
    payPartTime: "Most food service work in Washington is part-time: about 95% of fast food and counter workers and 89% of dishwashers worked part-time in the past year.",
    payWhy: "Washington law requires employers with 15 or more employees to post a wage range and a description of benefits on every job posting. On NoProbJobs, pay is shown only when the employer states it — never estimated.",

    whosHiringHeading: "Who’s hiring",
    whosHiringFallback: "Food service hiring in Washington comes from restaurants, quick-service chains, coffee shops, and the companies that run cafeterias for hospitals, schools and offices. See every current opening on the food service board.",
    seasonalNote: null,

    stepsHeading: "How hiring usually works",
    stepsIntro: "Every employer is different, but food service hiring usually looks like this:",
    steps: [
      ["Apply online or in person.", "You’ll give your contact info and your availability. Early mornings, late nights, weekends and holidays are common shifts, so the more of those you can cover, the better."],
      ["Short interview with a manager.", "Expect questions about customer service, teamwork, and how you handle a rush. School, volunteer or life examples count."],
      ["A trial shift (sometimes).", "Some kitchens ask you to work a short shift before they decide. Ask ahead of time whether it’s paid."],
      ["Start and get your cards.", "Get your Food Worker Card within 14 days of starting, and a MAST permit if you’ll serve alcohol. Training happens on the job."],
    ],
    stepsNote: "Timelines vary by employer.",

    tipsHeading: "How to land a food service job with no experience",
    tips: [
      ["Lead with availability.", "Early, late, weekends and holidays are the hardest shifts to fill."],
      ["Get your Food Worker Card early (optional).", "It’s $10 and not required until 14 days after you start, but having it already shows you’re ready to go."],
      ["Apply to several places at once.", "Counter, kitchen and cafeteria jobs all count, and cafeteria jobs often run on steadier weekday schedules."],
      ["Answer with real examples.", "Staying calm under pressure, working as a team, being on time. Managers want reliable people who can handle a rush."],
      ["Show up ready to work.", "On time, phone away, clean clothes. Some interviews turn into a quick look at the kitchen."],
      ["Follow up.", "A short call or stop-in a few days later is normal in food service."],
    ],

    leadsHeading: "Where food service can lead",
    leadsIntro: "Food service has clear steps up, in Washington pay terms:",
    leadsPaths: [
      ["Counter or crew", "Shift lead / food service supervisor (typical $29/hr)", "Food service manager (typical $36/hr; usually takes several years of food service experience)"],
      ["Dishwasher or prep", "Line cook (typical $25/hr)", "Chef or head cook (typical $32/hr)"],
    ],
    leadsNote: null,
  },

  faqHeading: "Getting Hired in Food Service FAQ",
  faq: [
    ["Do I need a food handlers card to apply for food service jobs in Washington?", "No. You need a Washington State Food Worker Card within 14 days of starting work, not before you apply."],
    ["How much does a Washington Food Worker Card cost?", "$10. The price is set by state rule and is the same in every county. Get it online at foodworkercard.wa.gov or through your local health department."],
    ["How long is a Washington Food Worker Card good for?", "Your first card lasts 2 years. If you renew before it expires, the renewal lasts 3 years, or 5 years with approved extra food safety training."],
    ["Do tips count toward minimum wage in Washington?", "No. Washington employers must pay at least the full minimum wage, and tips are yours on top of it."],
    ["Can I serve alcohol with no experience?", "Yes, with a MAST permit. Servers 18 to 20 can get a Class 13 permit to serve beer and wine at tables. Bartending takes a Class 12 permit, which requires being 21 or older."],
    ["Are most food service jobs part-time?", "Many are. About 95% of fast food and counter workers in Washington worked part-time in the past year. Full-time roles are available and are labeled on each job."],
  ],
  },

  security: {
  market: "WA",
  marketName: "Washington",
  marketSlug: "washington",
  category: "Security",
  categoryName: "Security",
  categoryNoun: "security",
  listingPath: "/washington/security/",

  metaTitle: "Security Jobs, No Experience Needed | Washington | NoProbJobs",
  metaDescription: "Security jobs in Washington hiring now, no experience required. Free alerts, apply direct with the employer.",

  h1: "Get Security Job Alerts",
  heroSub: "Be first to know when new No Experience Required Security Jobs show up in your area.",
  formButton: "Get free alerts",
  cadence: "as they’re posted",

  valueProps: [
    ["100% free", "Always free for job seekers."],
    ["No sign-up needed to apply", "Apply directly with the employer."],
    ["Real employers, real jobs", "Every job comes from the company’s own careers page."],
    ["Requirements up front", "Spend less time searching and more time applying."],
    ["Pay transparency", "Shown when the employer states it. Never estimated."],
  ],
  secondSignupHeading: "Get new security jobs before they fill.",

  info: {
    heading: "The Security Job Market in Washington State",

    whatTheWork: "Security officers watch over buildings, stores, hospitals, campuses, events and job sites. The work includes patrolling, checking IDs and visitors, answering alarms, writing incident reports, helping people find their way, and calling for help in an emergency. Many buildings are open around the clock, so night shifts are common. Most employers train new officers on the job, and most people learn the work in a few weeks.",

    credential: {
      heading: "The Washington security guard license",
      parts: [
        ["para", "If you work for a security company that provides guards to other businesses, Washington requires a Department of Licensing (DOL) security guard license. You don’t need it to apply, and you can’t get it on your own first: you need a job offer from a licensed security company."],
        ["steps", "How it works for an unarmed guard:", [
          ["Get a job offer", "from a licensed private security guard company. You must be at least 18."],
          ["Complete 8 hours of pre-assignment training", "from a DOL-certified trainer. Many companies run this in-house."],
          ["Apply for your license.", "The application fee is $101. DOL can take up to 60 days to issue it."],
          ["Start working on a temporary card.", "Once training is done and your application is in, your company can issue a temporary registration card that lets you work for up to 60 days while DOL processes your license."],
          ["Finish 8 more hours of training", "after you start, and then 4 hours of refresher training each year."],
        ]],
        ["callout", null, "The license renews every year (renewal fee $95). Ask the employer whether they cover the training and license fee."],
        ["para", "Armed security", "is a separate step: you must be 21 or older and hold a firearms certificate from the Washington State Criminal Justice Training Commission. Most no-experience security jobs are unarmed."],
        ["para", "In-house security:", "some guards employed directly by a single business, rather than by a security company, may not need this license. The employer will tell you what applies."],
      ],
    },

    payHeading: "What security pays in Washington",
    payIntro: null,
    payTable: [
      ["Washington minimum wage (2026)", "$17.13/hr statewide", "2027 rate announced Sep 30, 2026"],
      ["Seattle minimum wage (2026)", "$21.30/hr", null],
      ["Security guards, Washington", "Half earn $21–$29/hr", null],
      ["Security supervisors, Washington", "Typically $31/hr; half earn $26–$40/hr", null],
    ],
    payPartTime: "Most security guards work full time, and night shifts are common.",
    payWhy: "Washington law requires employers with 15 or more employees to post a wage range and a description of benefits on every job posting. On NoProbJobs, pay is shown only when the employer states it — never estimated.",

    whosHiringHeading: "Who’s hiring",
    whosHiringFallback: "Security hiring in Washington comes from contract security companies that staff offices, stores, hospitals, campuses and events, plus businesses that hire their own security teams. See every current opening on the security board.",
    seasonalNote: null,

    stepsHeading: "How hiring usually works",
    stepsIntro: "Every company is different, but security hiring usually looks like this:",
    steps: [
      ["Apply online.", "You’ll give your contact info and your availability. Nights, weekends and holidays are common, so be clear about what you can cover."],
      ["Interview.", "Expect questions about staying calm, following procedures, writing things down clearly, and dealing with difficult people. School, volunteer or life examples count."],
      ["Background check.", "Security companies check backgrounds as part of hiring and licensing."],
      ["Training and license.", "Complete the 8-hour pre-assignment training, submit your license application, and start on a temporary card while DOL processes it."],
    ],
    stepsNote: "Timelines vary by employer. The license itself can take up to 60 days, but the temporary card lets you work in the meantime.",

    tipsHeading: "How to land a security job with no experience",
    tips: [
      ["Lead with reliability.", "Security is about showing up on time for every shift. Say so, and back it up with an example."],
      ["Be open about shifts.", "Nights, weekends and overnight posts are the easiest to fill and the fastest way in."],
      ["Apply to security companies, not just businesses.", "Contract security companies hire the most guards and handle the licensing with you."],
      ["Ask about training and fees up front.", "Find out who pays for the 8-hour training and the $101 license."],
      ["Talk about calm and communication.", "Managers want people who stay steady, follow instructions, and write clear reports."],
      ["Follow up.", "A short call or email a few days after applying is normal."],
    ],

    leadsHeading: "Where security can lead",
    leadsIntro: "Security has clear steps up, in Washington pay terms:",
    leadsPaths: [
      ["Unarmed officer", "Site lead or security supervisor (typical $31/hr in Washington)"],
    ],
    leadsNote: "Armed officer is a separate path: 21 or older, with a state firearms certificate.",
  },

  faqHeading: "Getting Hired in Security FAQ",
  faq: [
    ["Do I need a license to apply for security jobs in Washington?", "No. You need a job offer from a licensed security company first. The company then helps you complete the 8-hour training and license application."],
    ["How much does a Washington security guard license cost?", "The application fee for an unarmed license is $101, and renewal is $95 a year. Ask your employer whether they cover it."],
    ["How long does it take to get a security guard license in Washington?", "DOL can take up to 60 days to issue a license. After you finish training and apply, your company can give you a temporary card that lets you work for up to 60 days while you wait."],
    ["How old do you have to be to work security in Washington?", "At least 18 for an unarmed license, and at least 21 for armed security."],
    ["Do security jobs require experience?", "Many don’t. Every job on this page is marked as not requiring experience, and most employers train new officers on the job."],
    ["Are security jobs full-time?", "Most security guards work full time, and night shifts are common. Part-time and on-call roles are labeled on each job."],
  ],
  },

  warehouse: {
  market: "WA",
  marketName: "Washington",
  marketSlug: "washington",
  category: "Warehouse",
  categoryName: "Warehouse",
  categoryNoun: "warehouse",
  listingPath: "/washington/warehouse/",

  metaTitle: "Warehouse Jobs, No Experience Needed | Washington | NoProbJobs",
  metaDescription: "Warehouse jobs in Washington hiring now, no experience required. Free alerts, apply direct with the employer.",

  h1: "Get Warehouse Job Alerts",
  heroSub: "Be first to know when new No Experience Required Warehouse Jobs show up in your area.",
  formButton: "Get free alerts",
  cadence: "as they’re posted",

  valueProps: [
    ["100% free", "Always free for job seekers."],
    ["No sign-up needed to apply", "Apply directly with the employer."],
    ["Real employers, real jobs", "Every job comes from the company’s own careers page."],
    ["Requirements up front", "Spend less time searching and more time applying."],
    ["Pay transparency", "Shown when the employer states it. Never estimated."],
  ],
  secondSignupHeading: "Get new warehouse jobs before they fill.",

  info: {
    heading: "The Warehouse Job Market in Washington State",

    whatTheWork: "Warehouse jobs keep products moving: unloading trucks, picking and packing orders, stocking shelves and racks, scanning and labeling, and loading outbound shipments. You’ll be on your feet and lifting through most of a shift. Work happens in distribution centers, fulfillment centers, store backrooms and stockrooms. Most places train you on the job, and schedules often include nights and weekends.",

    credential: {
      heading: "Forklifts and your rights on the floor",
      parts: [
        ["para", "You don’t need a forklift card to apply.", "Under workplace safety rules, your employer must train you, evaluate you on their equipment, and certify that you’re competent before you operate a forklift. That evaluation repeats at least every 3 years. Many entry warehouse jobs don’t involve forklifts at all."],
        ["para", "Washington’s warehouse quota law.", "At larger warehouse distribution centers that set production quotas (sometimes called a “rate”), Washington law says your employer:"],
        ["bullets", [
          "Must give you a written description of your quota when you’re hired, in your preferred language",
          "Must build in time for rest breaks, bathroom use, and walking to and from break areas",
          "Cannot discipline or fire you for missing a quota they didn’t properly give you in writing",
          "Must give you your work speed data if you ask",
        ]],
        ["para", "This covers employers with at least 100 nonexempt workers at one Washington warehouse distribution center, or 1,000 across the state. Warehouses that don’t use quotas aren’t covered."],
      ],
    },

    payHeading: "What warehouse work pays in Washington",
    payIntro: null,
    payTable: [
      ["Washington minimum wage (2026)", "$17.13/hr statewide", "2027 rate announced Sep 30, 2026"],
      ["Seattle minimum wage (2026)", "$21.30/hr", null],
      ["Laborers and material movers", "Average $20/hr; half earn $17–$22/hr", null],
      ["Stockers and order fillers", "Typically $24/hr; half earn $20–$26/hr", null],
      ["Hand packers and packagers", "Typically $19/hr; half earn $17–$21/hr", null],
      ["Warehouse supervisors (laborers and material movers)", "Typically $38/hr; half earn $27–$44/hr", null],
    ],
    payPartTime: "Many warehouse workers are full time, and part-time work is common too. Night and weekend shifts are regular.",
    payWhy: "Washington law requires employers with 15 or more employees to post a wage range and a description of benefits on every job posting. On NoProbJobs, pay is shown only when the employer states it — never estimated.",

    whosHiringHeading: "Who’s hiring",
    whosHiringFallback: "Warehouse hiring in Washington comes from distribution and fulfillment centers, retailers’ supply chains, and store stockrooms. See every current opening on the warehouse board.",
    seasonalNote: null,

    stepsHeading: "How hiring usually works",
    stepsIntro: "Every employer is different, but warehouse hiring usually looks like this:",
    steps: [
      ["Apply online.", "You’ll give your contact info and your availability. Shift choice (day, night, weekend) often matters as much as anything else."],
      ["Short screening or interview.", "Some warehouses do a quick interview; some large ones hire with little or none. Expect questions about reliability, safety and physical work."],
      ["Pre-hire steps (sometimes).", "Some employers run a background check or drug test before your start date."],
      ["Start and train.", "Safety training and on-the-job training happen once you’re hired, including any equipment training."],
    ],
    stepsNote: "Timelines vary by employer.",

    tipsHeading: "How to land a warehouse job with no experience",
    tips: [
      ["Be open about shifts.", "Nights, weekends and overnight shifts are the easiest to get and sometimes pay more. Check each listing."],
      ["Show you’re reliable.", "Attendance matters more than experience in warehouse work."],
      ["Be honest about physical work.", "Lifting, standing and walking all shift are normal. Say what you can do."],
      ["Apply to several at once.", "Warehouses hire in volume, especially ahead of the holidays."],
      ["Ask about the quota.", "If the job has a rate, ask what it is. At covered warehouses you’re entitled to it in writing."],
      ["Follow up.", "A short call or email a few days after applying is normal."],
    ],

    leadsHeading: "Where warehouse work can lead",
    leadsIntro: "Warehouse work has clear steps up, in Washington pay terms:",
    leadsPaths: [
      ["Picker, packer or material handler", "Stocker / order filler (typical $24/hr)", "Equipment operator (forklift and other trucks, employer-trained)", "Lead or supervisor (typical $38/hr in Washington)"],
    ],
    leadsNote: null,
  },

  faqHeading: "Getting Hired in Warehouse FAQ",
  faq: [
    ["Do I need forklift certification to get a warehouse job?", "No. Your employer must train and evaluate you on their own equipment before you drive a forklift, and many warehouse jobs don’t use forklifts at all."],
    ["Can a warehouse fire me for missing a quota in Washington?", "At covered warehouse distribution centers, your employer must give you your quota in writing and can’t discipline or fire you for missing a quota they didn’t properly disclose. Quotas must also allow time for breaks and bathroom use."],
    ["How much do warehouse jobs pay in Washington?", "At least $17.13 an hour statewide in 2026, and more in cities with higher minimums, like Seattle at $21.30. Stockers and order fillers in Washington typically earn about $24 an hour."],
    ["Are warehouse jobs full-time?", "Many are, and part-time roles are common too. Shift and schedule are labeled on each job."],
    ["Do warehouse jobs require experience?", "Many don’t. Every job on this page is marked as not requiring experience, and most employers train you on the job."],
  ],
  },

  grocery: {
  market: "WA", marketName: "Washington", marketSlug: "washington",
  category: "Grocery", categoryName: "Grocery", categoryNoun: "grocery",
  listingPath: "/washington/grocery/",
  metaTitle: "Grocery Jobs, No Experience Needed | Washington | NoProbJobs",
  metaDescription: "Grocery jobs in Washington hiring now, no experience required. Free alerts, apply direct with the employer.",
  h1: "Get Grocery Job Alerts",
  heroSub: "Be first to know when new No Experience Required Grocery Jobs show up in your area.",
  formButton: "Get free alerts",
  cadence: "as they’re posted",
  valueProps: VALUE_PROPS,
  secondSignupHeading: "Get new grocery jobs before they fill.",
  info: {
    heading: "The Grocery Job Market in Washington State",
    whatTheWork: "Grocery stores hire for a lot of different jobs under one roof: cashier and courtesy clerk at the front end, overnight and day stockers, deli, bakery, meat and seafood counters, produce, online order pickers, and fuel centers. Larger stores that sell general merchandise also hire for apparel, home goods, garden centers and liquor departments. Most stores train you on the job.",
    credential: {
      heading: "Cards, alcohol and unions",
      parts: [
        ["para", "Food Worker Card.", "If your job involves unpackaged food, food equipment or utensils, or surfaces where unwrapped food goes, Washington requires a Food Worker Card within 14 days of starting. In a grocery store that usually means deli, bakery, meat, seafood and produce. It costs $10 at foodworkercard.wa.gov or your local health department. Your first card lasts 2 years. You don’t need it to apply, and your employer will tell you if your role needs one."],
        ["para", "Selling alcohol at 18.", "Grocery workers 18 to 20 can sell, stock and handle beer and wine as long as someone 21 or older is on duty supervising. In stores that sell spirits, 18- to 20-year-olds can sell, stock and handle spirits when at least two supervisors 21 or older are on duty."],
        ["para", "Unions.", "Many large grocery stores in Washington, including Fred Meyer, QFC, Safeway and Albertsons locations, are covered by union contracts (UFCW 3000 and UFCW 367). In union stores, pay usually follows a contract wage scale that moves up as you log hours. Ask during hiring whether the store is union and how the pay scale works."],
      ],
    },
    payHeading: "What grocery pays in Washington",
    payIntro: null,
    payTable: [
      ["Washington minimum wage (2026)", "$17.13/hr statewide", "2027 rate announced Sep 30, 2026"],
      ["Seattle minimum wage (2026)", "$21.30/hr", null],
      ["Cashiers", "Average $22/hr; half earn $17–$23/hr", null],
      ["Stockers and order fillers", "Typically $24/hr; half earn $20–$26/hr", null],
      ["Food preparation (deli)", "Typically $23/hr; half earn $19–$25/hr", null],
      ["Bakers", "Typically $23/hr; half earn $19–$25/hr", null],
      ["Meat and fish cutters and trimmers", "Typically $22/hr; half earn $19–$23/hr", null],
    ],
    payPartTime: "These are statewide figures across all employers in each job, not grocery-only.",
    payWhy: PAY_WHY,
    whosHiringHeading: "Who’s hiring",
    whosHiringFallback: "Grocery hiring in Washington comes from supermarket chains and neighborhood grocers across the state. See every current opening on the grocery board.",
    seasonalNote: null,
    stepsHeading: "How hiring usually works",
    stepsIntro: "Every store is different, but grocery hiring usually looks like this:",
    steps: [
      ["Apply online.", "You’ll give your contact info and your availability. Early mornings, overnight stocking, evenings and weekends are the shifts stores most need."],
      ["Short assessment or screening (sometimes).", "Large chains may ask customer service and availability questions online."],
      ["Interview with a store manager.", "Often short. Expect questions about customer service, teamwork and reliability. School, volunteer or life examples count."],
      ["Start and train.", "Training happens on the job. Get your Food Worker Card within 14 days if your department needs one."],
    ],
    stepsNote: "Timelines vary by employer.",
    tipsHeading: "How to land a grocery job with no experience",
    tips: [
      ["Lead with availability.", "Overnight stocking, early mornings and weekends are the easiest ways in."],
      ["Look beyond the register.", "Courtesy clerk, stocker, deli, bakery, produce and online order picking all hire without experience."],
      ["Apply to more than one department.", "One store can have several openings at once."],
      ["Get your Food Worker Card early (optional).", "It’s $10, and having it makes you ready for deli, bakery and meat openings on day one."],
      ["Answer with real examples.", "Helping someone, working as a team, showing up on time."],
      ["Follow up.", "A short call or stop-in a few days after applying is normal in grocery."],
    ],
    leadsHeading: "Where grocery can lead",
    leadsIntro: "Grocery has clear steps up, in Washington pay terms:",
    leadsPaths: [
      ["Courtesy clerk or cashier", "Clerk / stocker (typical $24/hr)", "Department lead or store supervisor (retail supervisors typical $30/hr in Washington)"],
      ["Meat counter", "Butcher / meat cutter (typical $28/hr; usually learned on the job)"],
    ],
    leadsNote: "In union stores, pay also moves up the contract wage scale as you work more hours.",
  },
  faqHeading: "Getting Hired in Grocery FAQ",
  faq: [
    ["Do I need experience to work at a grocery store in Washington?", "No. Courtesy clerk, cashier, stocker, deli and produce jobs usually train you on the job. Every job on this page is marked as not requiring experience."],
    ["Do grocery workers need a food handlers card in Washington?", "If you work with unpackaged food, like in deli, bakery, meat, seafood or produce, you need a Washington Food Worker Card within 14 days of starting. It costs $10. Your employer will tell you if your role needs one."],
    ["Can you sell alcohol at a grocery store at 18 in Washington?", "Yes. Workers 18 to 20 can sell, stock and handle beer and wine when someone 21 or older is supervising. For spirits, at least two supervisors 21 or older must be on duty."],
    ["Are grocery jobs in Washington union?", "Many are. Large chains like Fred Meyer, QFC, Safeway and Albertsons have union contracts covering many of their Washington stores. Ask during hiring."],
    ["How much do grocery jobs pay in Washington?", "At least $17.13 an hour statewide in 2026, and more in cities with higher minimums, like Seattle at $21.30. Stockers in Washington typically earn about $24 an hour."],
  ],
  },

  "transportation-automotive": {
  market: "WA", marketName: "Washington", marketSlug: "washington",
  category: "Transportation/Automotive", categoryName: "Transportation & Automotive", categoryNoun: "transportation and automotive",
  listingPath: "/washington/transportation-automotive/",
  metaTitle: "Driving & Automotive Jobs, No Experience Needed | Washington | NoProbJobs",
  metaDescription: "Driving and automotive jobs in Washington hiring now, no experience required. Free alerts, apply direct with the employer.",
  h1: "Get Driving & Automotive Job Alerts",
  heroSub: "Be first to know when new No Experience Required Driving & Automotive Jobs show up in your area.",
  formButton: "Get free alerts",
  cadence: "as they’re posted",
  valueProps: VALUE_PROPS,
  secondSignupHeading: "Get new driving and automotive jobs before they fill.",
  info: {
    heading: "The Transportation & Automotive Job Market in Washington State",
    whatTheWork: "This category covers two kinds of work. Driving: delivering packages, parts or food in a van, box truck or your own car, and shuttling vehicles. Automotive: car washes and detailing, quick-lube and tire shops, auto parts counters, and dealership lot and porter jobs. Most employers train you on their routes, equipment and systems.",
    credential: {
      heading: "Licenses: what you need and what you don’t",
      parts: [
        ["bullets", [
          ["Most driving jobs need a valid driver’s license,", "and employers usually check your driving record. Van and light-truck delivery jobs generally don’t need a commercial license."],
          ["A CDL (commercial driver’s license)", "is only needed for heavy trucks and some larger vehicles. In Washington you can get one at 18 to drive within the state and 21 to drive across state lines or haul hazardous materials."],
          ["Getting a CDL takes training.", "Since February 2022, first-time CDL applicants must complete federal Entry-Level Driver Training before the skills test. Some employers run their own training programs; if a listing mentions paid CDL training, ask who pays and what you commit to in return."],
          ["Automotive jobs", "like car wash, lube tech and parts counter usually need no license beyond a regular driver’s license, if that."],
          ["Delivery in your own car:", "some of these are employee jobs and some are independent contractor gigs. Check the listing. Contractor work isn’t covered by minimum wage the same way employee jobs are."],
        ]],
      ],
    },
    payHeading: "What transportation and automotive pays in Washington",
    payIntro: null,
    payTable: [
      ["Washington minimum wage (2026)", "$17.13/hr statewide", "2027 rate announced Sep 30, 2026"],
      ["Seattle minimum wage (2026)", "$21.30/hr", null],
      ["Cleaners of vehicles (car wash, detail)", "Typically $23/hr; half earn $18–$25/hr", null],
      ["Automotive service attendants (lube, fuel)", "Typically $23/hr; half earn $18–$24/hr", null],
      ["Parts salespersons", "Typically $27/hr; half earn $19–$32/hr", null],
      ["Light truck and delivery drivers", "Typically $28/hr; half earn $23–$31/hr", null],
    ],
    payPartTime: null,
    payWhy: PAY_WHY,
    whosHiringHeading: "Who’s hiring",
    whosHiringFallback: "Driving and automotive hiring in Washington comes from delivery companies, car washes, quick-lube and tire shops, parts stores and dealerships. See every current opening on the transportation board.",
    seasonalNote: null,
    stepsHeading: "How hiring usually works",
    stepsIntro: "Every employer is different, but hiring usually looks like this:",
    steps: [
      ["Apply online.", "You’ll give your contact info, availability, and for driving jobs, your driver’s license details."],
      ["Driving record check.", "For driving roles, employers usually review your record."],
      ["Short interview.", "Expect questions about reliability, safety and customer service."],
      ["Pre-hire steps (sometimes).", "Some employers run a background check or drug test. Commercial driving jobs require a DOT physical."],
      ["Ride-along or training.", "Most drivers and shop staff train with someone experienced before working solo."],
    ],
    stepsNote: "Timelines vary by employer.",
    tipsHeading: "How to land a transportation or automotive job with no experience",
    tips: [
      ["Keep your license and record clean.", "It’s the first thing driving employers check."],
      ["Start where training is built in.", "Car wash, lube and parts-counter jobs teach you the basics and lead to shop and driving roles."],
      ["Be open about early starts.", "Delivery routes often start early in the morning."],
      ["Know the area.", "Mention if you know the local roads well."],
      ["Ask about paid training.", "Some employers pay for further training, including CDL. Get the terms in writing."],
      ["Follow up.", "A short call a few days after applying is normal."],
    ],
    leadsHeading: "Where transportation and automotive can lead",
    leadsIntro: "In Washington pay terms:",
    leadsPaths: [
      ["Car wash or lube tech", "Parts counter (typical $27/hr) or shop roles"],
      ["Van or light-truck delivery (typical $28/hr)", "CDL driver (heavy and tractor-trailer drivers typical $38/hr; requires a CDL)"],
    ],
    leadsNote: null,
  },
  faqHeading: "Getting Hired in Driving & Automotive FAQ",
  faq: [
    ["Do I need a CDL for delivery driver jobs in Washington?", "Usually not. Van and light-truck delivery jobs generally need a regular driver’s license. A CDL is needed for heavy trucks."],
    ["How old do you have to be to get a CDL in Washington?", "18 to drive within Washington, and 21 to drive across state lines or haul hazardous materials."],
    ["Do I need experience to work at a car wash or lube shop?", "No. These jobs usually train you on the job. Every job on this page is marked as not requiring experience."],
    ["What is paid CDL training?", "Some employers pay for the training you need to get a commercial license. Terms vary, so ask what you’re agreeing to before you sign."],
  ],
  },

  sales: {
  market: "WA", marketName: "Washington", marketSlug: "washington",
  category: "Sales", categoryName: "Sales", categoryNoun: "sales",
  listingPath: "/washington/sales/",
  metaTitle: "Sales Jobs, No Experience Needed | Washington | NoProbJobs",
  metaDescription: "Sales jobs in Washington hiring now, no experience required. Free alerts, apply direct with the employer.",
  h1: "Get Sales Job Alerts",
  heroSub: "Be first to know when new No Experience Required Sales Jobs show up in your area.",
  formButton: "Get free alerts",
  cadence: "as they’re posted",
  valueProps: VALUE_PROPS,
  secondSignupHeading: "Get new sales jobs before they fill.",
  info: {
    heading: "The Sales Job Market in Washington State",
    whatTheWork: "Sales jobs are about helping customers choose and buy: talking with people in a store or showroom, explaining products or plans (phones, furniture, appliances, memberships), answering questions, and closing the sale. Some jobs are in stores, some on the phone. Many pay an hourly wage plus commission or bonuses. Most employers train you on their products and sales process.",
    credential: {
      heading: "Commission pay in Washington",
      parts: [
        ["bullets", [
          ["You’re still owed minimum wage.", "In Washington, employees paid partly or fully on commission must earn at least minimum wage for every hour worked. Your total pay for the pay period, divided by the hours you worked, has to reach the minimum wage. If it doesn’t, the employer pays the difference."],
          ["The exception is outside sales.", "People whose job is selling away from the employer’s location (true outside sales roles) are exempt from this rule. Most no-experience sales jobs are in-store or on the phone and are not outside sales."],
          ["Ask how pay works.", "Before you accept, ask what the base pay is, how commission is calculated, and how often it’s paid."],
        ]],
      ],
    },
    payHeading: "What sales pays in Washington",
    payIntro: null,
    payTable: [
      ["Washington minimum wage (2026)", "$17.13/hr statewide", "2027 rate announced Sep 30, 2026"],
      ["Seattle minimum wage (2026)", "$21.30/hr", null],
      ["Retail salespersons", "Typically $22/hr; half earn $18–$24/hr", null],
      ["Counter and rental clerks", "Typically $26/hr; half earn $20–$29/hr", null],
      ["Parts salespersons", "Typically $27/hr; half earn $19–$32/hr", null],
    ],
    payPartTime: "Pay in sales often varies more than in other jobs because of commission.",
    payWhy: PAY_WHY,
    whosHiringHeading: "Who’s hiring",
    whosHiringFallback: "Sales hiring in Washington comes from specialty retailers, wireless and service providers, rental counters and parts stores. See every current opening on the sales board.",
    seasonalNote: null,
    stepsHeading: "How hiring usually works",
    stepsIntro: "Every employer is different, but sales hiring usually looks like this:",
    steps: [
      ["Apply online.", "You’ll give your contact info and your availability. Evenings and weekends are usually the busiest selling times."],
      ["Screening call or assessment (sometimes).", "Some employers ask a few questions about how you’d handle a customer."],
      ["Interview.", "Expect to talk about helping people, handling “no,” and working toward goals. Some interviewers ask you to “sell” them something simple."],
      ["Start and train.", "Product and sales training happen on the job."],
    ],
    stepsNote: "Timelines vary by employer.",
    tipsHeading: "How to land a sales job with no experience",
    tips: [
      ["Show you like talking to people.", "It’s the core of the job."],
      ["Be ready for “sell me this.”", "Ask a question about what the person needs before you pitch."],
      ["Use real examples.", "Convincing a team, fundraising, helping a friend choose something. It all counts."],
      ["Ask about pay structure.", "Base, commission, bonus, and when each is paid."],
      ["Be open about evenings and weekends.", "That’s when stores sell the most."],
      ["Follow up.", "A short thank-you message after the interview helps in sales more than anywhere."],
    ],
    leadsHeading: "Where sales can lead",
    leadsIntro: "Sales has clear steps up, in Washington pay terms:",
    leadsPaths: [
      ["Sales associate", "Senior associate or shift lead", "Retail sales supervisor (typical $30/hr in Washington)"],
    ],
    leadsNote: "Sales experience also carries over to customer service roles (typical $28/hr in Washington) and to sales representative roles, which usually require some experience first.",
  },
  faqHeading: "Getting Hired in Sales FAQ",
  faq: [
    ["Do commission sales jobs pay minimum wage in Washington?", "Yes, for most employees. Your total pay for the pay period divided by hours worked must reach at least the minimum wage, or the employer pays the difference. True outside sales roles are the exception."],
    ["Can I get a sales job with no experience?", "Yes. Many sales associate and in-store sales jobs train you on the job. Every job on this page is marked as not requiring experience."],
    ["What’s the difference between sales and retail jobs?", "Sales jobs focus on selling products or plans and often include commission or bonuses. Retail jobs cover more of running a store: registers, stocking and customer help."],
    ["What questions should I ask about commission?", "Ask what the base pay is, how commission is calculated, when it’s paid, and whether there’s a sales goal."],
  ],
  },

  facilities: {
  market: "WA", marketName: "Washington", marketSlug: "washington",
  category: "Facilities", categoryName: "Facilities", categoryNoun: "facilities",
  listingPath: "/washington/facilities/",
  metaTitle: "Facilities Jobs, No Experience Needed | Washington | NoProbJobs",
  metaDescription: "Facilities jobs in Washington hiring now, no experience required. Free alerts, apply direct with the employer.",
  h1: "Get Facilities Job Alerts",
  heroSub: "Be first to know when new No Experience Required Facilities Jobs show up in your area.",
  formButton: "Get free alerts",
  cadence: "as they’re posted",
  valueProps: VALUE_PROPS,
  secondSignupHeading: "Get new facilities jobs before they fill.",
  info: {
    heading: "The Facilities Job Market in Washington State",
    whatTheWork: "Facilities jobs keep buildings and grounds running: cleaning offices, schools, hospitals, stores and hotels; housekeeping; emptying trash and restocking supplies; basic maintenance like changing lights and small repairs; and groundskeeping like mowing, planting and clearing walkways. Many cleaning jobs run on evening or overnight shifts, after buildings close. Most employers train you on the job.",
    credential: {
      heading: "Chemical safety training",
      parts: [
        ["para", "Cleaning products can be hazardous. In Washington, employers must give you training on the hazardous chemicals in your work area when you start, and again whenever a new chemical hazard is added. That includes how to recognize hazards, how to protect yourself, and where to find safety information for each product. You don’t need any certification to apply."],
      ],
    },
    payHeading: "What facilities work pays in Washington",
    payIntro: null,
    payTable: [
      ["Washington minimum wage (2026)", "$17.13/hr statewide", "2027 rate announced Sep 30, 2026"],
      ["Seattle minimum wage (2026)", "$21.30/hr", null],
      ["Janitors and cleaners", "Typically $24/hr; half earn $19–$27/hr", null],
      ["Housekeeping cleaners", "Average $24/hr; half earn $18–$24/hr", null],
      ["Landscaping and groundskeeping", "Typically $26/hr; half earn $20–$29/hr", null],
      ["Housekeeping and janitorial supervisors", "Typically $30/hr; half earn $21–$34/hr", null],
    ],
    payPartTime: null,
    payWhy: PAY_WHY,
    whosHiringHeading: "Who’s hiring",
    whosHiringFallback: "Facilities hiring in Washington comes from cleaning and building-services companies, hospitals, schools, hotels and property managers. See every current opening on the facilities board.",
    seasonalNote: null,
    stepsHeading: "How hiring usually works",
    stepsIntro: "Every employer is different, but facilities hiring usually looks like this:",
    steps: [
      ["Apply online.", "You’ll give your contact info and your availability. Evening and overnight shifts are common for cleaning."],
      ["Short interview.", "Expect questions about reliability, working independently and attention to detail."],
      ["Pre-hire steps (sometimes).", "Buildings like hospitals and schools may require a background check before you start."],
      ["Start and train.", "You’ll learn the building, equipment and cleaning products on the job, including chemical safety training."],
    ],
    stepsNote: "Timelines vary by employer.",
    tipsHeading: "How to land a facilities job with no experience",
    tips: [
      ["Be open about evening and overnight shifts.", "They’re the most common in cleaning and the easiest to get."],
      ["Show you’re reliable and can work on your own.", "Many facilities jobs are solo or small-team."],
      ["Mention anything hands-on.", "Cleaning, yard work, fixing things at home. It counts."],
      ["Apply to building-services companies too.", "They staff many buildings at once and hire often."],
      ["Ask about the route or building.", "Know whether you’d stay in one building or move between sites."],
      ["Follow up.", "A short call a few days after applying is normal."],
    ],
    leadsHeading: "Where facilities work can lead",
    leadsIntro: "In Washington pay terms:",
    leadsPaths: [
      ["Cleaner or housekeeper", "Lead or supervisor (typical $30/hr)"],
      ["Cleaner or grounds worker", "General maintenance worker (typical $34/hr; usually needs some hands-on skills, often learned on the job)"],
    ],
    leadsNote: null,
  },
  faqHeading: "Getting Hired in Facilities FAQ",
  faq: [
    ["Do I need experience for janitorial jobs in Washington?", "No. Most cleaning and custodial jobs train you on the job. Every job on this page is marked as not requiring experience."],
    ["Do I need a certification to be a janitor or housekeeper?", "No. Your employer must train you on the cleaning chemicals you’ll use when you start."],
    ["Are cleaning jobs at night?", "Many are. Offices, stores and schools are often cleaned in the evening or overnight after they close. Shifts are labeled on each job."],
    ["How much do janitors make in Washington?", "At least $17.13 an hour statewide in 2026, and more in cities with higher minimums, like Seattle at $21.30. Janitors and cleaners in Washington typically earn about $24 an hour."],
  ],
  },

  healthcare: {
  market: "WA", marketName: "Washington", marketSlug: "washington",
  category: "Healthcare", categoryName: "Healthcare", categoryNoun: "healthcare",
  listingPath: "/washington/",   // sector, not a board category — links go to the WA board
  metaTitle: "Hospital & Healthcare Jobs, No Experience Needed | Washington | NoProbJobs",
  metaDescription: "Non-clinical hospital and healthcare jobs in Washington hiring now, no experience required. Free alerts, apply direct with the employer.",
  h1: "Get Hospital & Healthcare Job Alerts",
  heroSub: "Be first to know when new No Experience Required Healthcare Jobs show up in your area.",
  formButton: "Get free alerts",
  cadence: "as they’re posted",
  valueProps: VALUE_PROPS,
  secondSignupHeading: "Get new healthcare jobs before they fill.",
  info: {
    heading: "The Healthcare Job Market in Washington State",
    whatTheWork: "Hospitals and clinics need a lot of people who aren’t nurses or doctors. No-experience healthcare jobs include patient transporters (moving patients by wheelchair or bed between units and tests), environmental services (cleaning patient rooms and keeping areas safe), food and nutrition services (preparing and delivering patient meals, running the cafeteria), and front desk and patient access (checking patients in, scheduling, answering phones). Employers train you on the job, including hospital safety and infection-control practices.",
    credential: {
      heading: "What hospitals check before you start",
      parts: [
        ["para", "Healthcare employers usually have more pre-hire steps than other jobs. At one large Washington health system, for example, job offers depend on:"],
        ["bullets", [
          ["A background check,", "including a search of Washington State Patrol records"],
          ["A drug screen,", "which at some health systems also tests for nicotine"],
          ["Employee health documents,", "including proof of immunizations and a health screening"],
        ]],
        ["para", "Requirements vary by employer and by role. You don’t need any of this to apply; it happens after an offer. Ask what’s required so you can gather your immunization records early."],
      ],
    },
    payHeading: "What healthcare support jobs pay in Washington",
    payIntro: null,
    payTable: [
      ["Washington minimum wage (2026)", "$17.13/hr statewide", "2027 rate announced Sep 30, 2026"],
      ["Seattle minimum wage (2026)", "$21.30/hr", null],
      ["Patient transporters (orderlies)", "Typically $28/hr; half earn $22–$31/hr", null],
      ["Receptionists and front desk", "Typically $25/hr; half earn $20–$27/hr", null],
      ["Cafeteria and institution cooks", "Typically $26/hr; half earn $21–$29/hr", null],
      ["Housekeeping cleaners", "Average $24/hr; half earn $18–$24/hr", null],
    ],
    payPartTime: "These are statewide figures across all employers in each job, not hospital-only.",
    payWhy: PAY_WHY,
    whosHiringHeading: "Who’s hiring",
    whosHiringFallback: "Healthcare hiring in Washington comes from hospitals, health systems, clinics and the companies that run their food and cleaning services. See every current opening on the healthcare board.",
    seasonalNote: null,
    stepsHeading: "How hiring usually works",
    stepsIntro: "Every employer is different, but healthcare hiring usually looks like this:",
    steps: [
      ["Apply online.", "You’ll give your contact info, work history and availability. Hospitals run around the clock, so nights, weekends and holidays are common."],
      ["Screening and interview.", "Often a phone or video screen, then an interview. Expect questions about reliability, teamwork, and staying calm and kind with people who are sick or stressed."],
      ["Offer, then pre-hire checks.", "Background check, drug screen and health documents, usually after the offer and before your start date."],
      ["Orientation and training.", "New employee orientation, then training on your unit."],
    ],
    stepsNote: "Healthcare hiring can take longer than retail or food service because of the pre-hire checks.",
    tipsHeading: "How to land a healthcare job with no experience",
    tips: [
      ["Start with support roles.", "Transport, environmental services, food service and front desk hire without experience."],
      ["Gather your immunization records now.", "It speeds up the steps after an offer."],
      ["Show you’re calm and caring.", "Real examples of helping someone who was upset or unwell count."],
      ["Be open about nights and weekends.", "Hospitals staff 24/7."],
      ["Apply to hospital service partners too.", "Some hospital cafeterias and cleaning teams are run by outside companies that hire separately."],
      ["Follow up.", "A short email a few days after applying is normal."],
    ],
    leadsHeading: "Where healthcare can lead",
    leadsIntro: "Support roles get you inside a hospital, where clinical roles are nearby:",
    leadsPaths: [
      ["Transporter, EVS or food service", "Lead or supervisor in the same department"],
    ],
    leadsNote: "Clinical roles like nursing assistant or medical assistant require state-approved training or certification. Some hospitals support employees who pursue it; ask.",
  },
  faqHeading: "Getting Hired in Healthcare FAQ",
  faq: [
    ["Can I work in a hospital with no experience in Washington?", "Yes. Patient transport, environmental services, food service and front desk jobs usually train you on the job. Every job on this page is marked as not requiring experience."],
    ["What do hospitals check before you start?", "Usually a background check, a drug screen and health documents including immunization records. Some health systems also test for nicotine. It varies by employer."],
    ["Do I need a certification to be a patient transporter?", "Typically no. Transporters are trained on the job."],
    ["How much do patient transporters make in Washington?", "Patient transporters (orderlies) in Washington typically earn about $28 an hour, with half earning between $22 and $31."],
  ],
  },

};
let CONTENT = PAGES.retail;   // reassigned in boot() from the URL

// UTM for every outbound listing link (spec). Computed lazily from the selected page.
function linkUtm(){ return "utm_source=alerts_page&utm_medium=internal&utm_campaign=" + CONTENT.market.toLowerCase() + "_" + CONTENT.categoryNoun.replace(/\s+/g, "_"); }
function withUtm(path){ return path + (path.indexOf("?") >= 0 ? "&" : "?") + linkUtm(); }

const CHEV = '<svg width="10" height="7" viewBox="0 0 10 7" fill="none" stroke="currentColor" stroke-width="1.6" style="flex:none" aria-hidden="true"><path d="M1 1.5 5 5.5l4-4"></path></svg>';
const CHEV_MUTED = '<svg width="10" height="7" viewBox="0 0 10 7" fill="none" stroke="var(--ink-muted)" stroke-width="1.6" style="flex:none" aria-hidden="true"><path d="M1 1.5 5 5.5l4-4"></path></svg>';
const ROW_CHECK = '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="var(--accent-ink)" stroke-width="2.2" aria-hidden="true"><path d="M3 8.4l3 3L13 4.6"></path></svg>';
const VP_CHECK = '<svg width="17" height="17" viewBox="0 0 16 16" fill="none" stroke="var(--mark-ink)" stroke-width="1.9"><circle cx="8" cy="8" r="6.6"></circle><path d="M5 8.3l2.1 2.1L11 6.1"></path></svg>';
const ARROW = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="var(--accent)" stroke-width="2.2" style="flex:none" aria-hidden="true"><path d="M3 8h10M9 4l4 4-4 4"></path></svg>';
const TICK = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="var(--accent)" stroke-width="2.6" style="flex:none" aria-hidden="true"><path d="M3 8.4l3 3L13 4.6"></path></svg>';

class AlertsApp extends React.Component {
  constructor(props){
    super(props);
    this.data = props.data || { count: 0, maxPay: null, recent: [], otherCats: [], whosHiring: [], seasonalCount: 0, pulledAt: null };
    this.state = {
      email: "", location: "",
      cats: [CONTENT.category],
      catOpen: false,
      phase: "form", error: "",
      logoOk: {},
      wide: window.matchMedia(BP).matches,
    };
    this.formRef = React.createRef();
    this.utm = this.readUtm();
  }

  readUtm(){
    const out = { utm_source: null, utm_medium: null, utm_campaign: null, utm_content: null, utm_term: null };
    try { const p = new URL(window.location.href).searchParams; Object.keys(out).forEach((k) => { out[k] = p.get(k); }); } catch (e) {}
    return out;
  }
  pagePath(){ try { return window.location.pathname || CONTENT.listingPath; } catch (e) { return CONTENT.listingPath; } }
  // Page + channel encoded into the existing `source` field — no Make changes. Channel from the
  // inbound utm_source (fb_groups, reddit, …): "alerts_wa_retail" or "alerts_wa_retail|fb_groups".
  signupSource(){
    const base = "alerts_" + CONTENT.market.toLowerCase() + "_" + CONTENT.categoryNoun.replace(/\s+/g, "_");
    const ch = (this.utm.utm_source || "").trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "");
    return ch ? base + "|" + ch : base;
  }

  componentDidMount(){
    this._mql = window.matchMedia(BP);
    this._onMql = () => this.setState({ wide: this._mql.matches });
    this._mql.addEventListener("change", this._onMql);
    window.addEventListener("mousedown", this.onDocDown, true);
    this.preflightLogos(this.data.recent || []);
  }
  componentWillUnmount(){
    if (this._mql) this._mql.removeEventListener("change", this._onMql);
    window.removeEventListener("mousedown", this.onDocDown, true);
    clearTimeout(this._t);
  }
  onDocDown = (e) => {
    if (!this.state.catOpen) return;
    const t = e.target;
    if (t && t.closest && (t.closest("[data-cat-pop]") || t.closest("[data-cat-trigger]"))) return;
    this.setState({ catOpen: false });
  };

  preflightLogos(recs){
    const seen = {};
    recs.forEach((r) => {
      if (R.localLogo(r.company_name)) return;
      const d = r.employer_domain;
      if (!d || seen[d] || !R.ownsDomain(r.company_name, d)) return;
      seen[d] = true;
      const img = new Image();
      img.onerror = () => {};
      img.onload = () => { if (img.naturalWidth < 16) return; this.setState((st) => { const ok = Object.assign({}, st.logoOk); ok[d] = true; return { logoOk: ok }; }); };
      img.src = R.logoUrl(d);
    });
  }

  // ── form handlers ─────────────────────────────────────────
  onEmail = (e) => this.setState({ email: e.target.value });
  onLocation = (e) => this.setState({ location: e.target.value });
  toggleCatOpen = () => this.setState({ catOpen: !this.state.catOpen });
  toggleCat = (c) => () => {
    const cur = this.state.cats || [];
    const next = cur.indexOf(c) >= 0 ? cur.filter((x) => x !== c) : cur.concat([c]);
    this.setState({ cats: next });
  };
  onKey = (e) => { if (e.key === "Enter") { e.preventDefault(); this.submit(); } };
  scrollToForm = () => { try { if (this.formRef.current) this.formRef.current.scrollIntoView({ behavior: "smooth", block: "center" }); } catch (e) {} };

  submit = () => {
    const email = (this.state.email || "").trim();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { this.setState({ phase: "form", error: "Enter a valid email address." }); return; }
    const location = (this.state.location || "").trim();
    if (!location) { this.setState({ phase: "form", error: "Enter a city or ZIP." }); return; }   // accepted even outside live markets — demand data
    const categories = (this.state.cats && this.state.cats.length) ? this.state.cats : [CONTENT.category];
    this.setState({ phase: "creating", error: "", catOpen: false });
    const wait = new Promise((r) => { this._t = setTimeout(r, 2000); });
    Promise.all([SB.captureAlert({ email, source: this.signupSource(), location, categories }), wait])
      .then(() => {
        // Full context (market/category/channel) recorded on the GA4 event; Make gets it via `source`.
        track(Object.assign({ event: "alert_signup", source_page: sourcePage(), market: CONTENT.market, category: CONTENT.category },
          this.utm.utm_source ? { channel: this.utm.utm_source } : {}));
        this.setState({ phase: "done" });
      })
      .catch(() => this.setState({ phase: "form", error: "Couldn’t save that — please try again." }));
  };

  // ── card shaping (mirrors landing.shape) ──────────────────
  shape(r){
    const domain = r.employer_domain || "";
    const local = R.localLogo(r.company_name);
    const logoSrc = local || R.logoUrl(domain);
    const showLogo = local ? true : (R.ownsDomain(r.company_name, domain) && !!this.state.logoOk[domain]);
    const jobHref = RT.jobPath(r) + "/";
    return Object.assign({}, r, {
      id: r.internal_id,
      company: R.companyLabel(r.company_name),
      cardTitle: R.cardTitle(r.title),
      logoImg: showLogo ? R.logoImg(logoSrc, 20) : null,
      showLogo, showMonogram: !showLogo,
      monogram: (r.company_name || "?").trim().charAt(0).toUpperCase(),
      locationLine: [L.cityName(r.city), r.state].filter(Boolean).join(", "),
      pay: R.money(r), posted: R.postedLabel(r.posted_at),
      isNew: !!r.is_new,
      expLabel: R.EXP_LABEL[r.experience_condition] || null,
      expStrong: r.experience_condition === "NONE_NEEDED" || r.experience_condition === "WAIVED",
      expSoft: r.experience_condition === "PREFERRED",
      href: jobHref,
      onCardClick: (e) => { if (e && (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button === 1)) return; if (e && e.preventDefault) e.preventDefault(); window.location.href = jobHref; },
      isSelected: false, open: () => { window.location.href = jobHref; },
      openKey: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); window.location.href = jobHref; } },
    });
  }

  // ── hero + signup form ────────────────────────────────────

  workTypeSelect(inputStyle){
    const picked = this.state.cats || [];
    const open = this.state.catOpen;
    const summary = picked.length ? (picked.length > 2 ? picked.slice(0, 2).join(", ") + " +" + (picked.length - 2) : picked.join(", ")) : CONTENT.categoryName;
    const checkbox = (on) => on
      ? h("span", { "aria-hidden": "true", style: s("flex:none;width:18px;height:18px;border-radius:3px;background:var(--ink);display:grid;place-items:center") }, raw(ROW_CHECK))
      : h("span", { "aria-hidden": "true", style: s("flex:none;width:18px;height:18px;border-radius:3px;border:1px solid var(--ink);background:var(--surface-raised)") });
    return h("div", { style: s("position:relative"), "data-cat-pop": "true" },
      h("button", { type: "button", "data-cat-trigger": "true", onClick: this.toggleCatOpen, "aria-expanded": open, "aria-haspopup": "true", className: "fc-bd-accent",
          style: s(inputStyle + ";display:flex;align-items:center;justify-content:space-between;gap:8px;cursor:pointer;text-align:left;font-weight:700") },
        h("span", { style: s("overflow:hidden;text-overflow:ellipsis;white-space:nowrap") }, summary), raw(open ? CHEV : CHEV_MUTED)),
      open && h("div", { role: "group", "aria-label": "Work type", style: s("margin-top:6px;border:1px solid var(--line);border-radius:3px;background:var(--surface-raised);max-height:230px;overflow-y:auto;-webkit-overflow-scrolling:touch;padding:6px") },
        h("div", { style: s("display:grid;grid-template-columns:1fr 1fr;gap:1px 8px") },
          R.CATEGORIES.map((c, i) => { const on = picked.indexOf(c) >= 0; return h("button", { key: i, type: "button", role: "checkbox", "aria-checked": on, onClick: this.toggleCat(c), className: "hv-bg-sunk",
              style: s("display:flex;align-items:center;gap:7px;min-height:38px;padding:0 5px;background:transparent;border:0;border-radius:3px;cursor:pointer;text-align:left") },
            checkbox(on),
            h("span", { style: s("flex:1;font-size:13px;font-weight:" + (on ? "700" : "500") + ";line-height:1.15;color:var(--ink)") }, c)); }))));
  }

  renderHeroForm(){
    // Softer than the site's brutalist box (per the CEO's landingfolio reference): 1px light
    // borders, rounded corners, generous spacing, a subtle lift — a clean signup card.
    const inputStyle = "box-sizing:border-box;width:100%;min-height:50px;padding:0 14px;border:1px solid var(--line);border-radius:10px;background:var(--surface);font-size:15px;color:var(--ink);outline:0";
    const field = (label, node) => h("label", { style: s("display:grid;gap:6px") },
      h("span", { style: s("font-size:12.5px;font-weight:700;letter-spacing:0.02em;color:var(--ink-muted)") }, label), node);
    const card = "width:100%;box-sizing:border-box;background:var(--surface-raised);border:1px solid var(--line);border-radius:16px;box-shadow:0 16px 44px rgba(10,58,117,0.13);padding:24px;display:grid;gap:14px";
    const cta = "min-height:52px;border-radius:11px;background:var(--accent);border:0;font-size:16px;font-weight:800;letter-spacing:0.01em;color:var(--accent-ink);text-decoration:none;display:flex;align-items:center;justify-content:center;gap:10px";
    const cadence = CONTENT.cadence;
    const microcopy = "Get Notified about New Jobs. Unsubscribe anytime.";

    if (this.state.phase === "done") {
      return h("div", { ref: this.formRef, style: s(card + ";justify-items:center;text-align:center;padding:30px 24px;gap:12px") },
        h("img", { src: "/logo.png", alt: "", width: 52, height: 52, style: s("width:52px;height:52px;object-fit:contain") }),
        h("div", { style: s("font-size:19px;font-weight:800;color:var(--ink)") }, "You’re on the list"),
        h("div", { style: s("font-size:15px;line-height:1.6;color:var(--ink-muted);text-wrap:pretty") }, "We’ll email new " + CONTENT.categoryNoun + " jobs " + cadence + "."),
        h("a", { href: withUtm(CONTENT.listingPath), style: s(cta + ";padding:0 22px") }, "See " + CONTENT.categoryNoun + " jobs"));
    }

    const creating = this.state.phase === "creating";
    return h("div", { ref: this.formRef, style: s(card) },
      h("div", { style: s("display:grid;gap:3px") },
        h("div", { style: s("font-family:var(--font-display);font-weight:800;font-size:19px;line-height:1.15;color:var(--ink)") }, "Free job alerts"),
        h("div", { style: s("font-size:13.5px;color:var(--ink-muted)") }, "New " + CONTENT.categoryNoun + " jobs, straight to your inbox.")),
      field("Email", h("input", { type: "email", value: this.state.email, onChange: this.onEmail, onKeyDown: this.onKey, placeholder: "you@example.com", className: "fc-bd-accent", disabled: creating, style: s(inputStyle) })),
      field("City or ZIP", h("input", { type: "text", value: this.state.location, onChange: this.onLocation, onKeyDown: this.onKey, placeholder: "e.g. Seattle or 98101", "aria-label": "City or ZIP", className: "fc-bd-accent", disabled: creating, style: s(inputStyle) })),
      field("Work type", this.workTypeSelect(inputStyle)),
      this.state.error && h("div", { role: "alert", style: s("font-size:14px;font-weight:600;color:var(--accent)") }, this.state.error),
      h("button", { type: "button", onClick: this.submit, disabled: creating, style: s(cta + ";cursor:" + (creating ? "default" : "pointer")) },
        creating ? h("span", { "aria-hidden": "true", style: s("width:20px;height:20px;border:3px solid rgba(255,255,255,0.4);border-top-color:var(--accent-ink);border-radius:50%;animation:spin 0.8s linear infinite") }) : null,
        creating ? "Creating alert…" : CONTENT.formButton),
      h("div", { style: s("font-size:12.5px;line-height:1.4;color:var(--ink-muted);text-align:center") }, microcopy));
  }

  renderHero(){
    const wide = this.state.wide;
    const payPill = this.data.maxPay
      ? h("span", { style: s("justify-self:start;display:inline-flex;align-items:center;padding:5px 12px;border-radius:999px;background:var(--mark);color:var(--mark-ink);font-size:13px;font-weight:800;letter-spacing:0.01em") }, "Up to $" + this.data.maxPay + " an hour")
      : null;
    const countLine = this.data.count
      ? h("div", { style: s("font-size:15px;line-height:1.5;color:var(--ink-muted);text-wrap:pretty") },
          h("strong", { style: s("color:var(--ink)") }, this.data.count.toLocaleString()), " " + CONTENT.categoryNoun + " jobs hiring in " + CONTENT.marketName + " right now. ",
          h("a", { href: withUtm(CONTENT.listingPath), style: s("font-weight:800;color:var(--accent);white-space:nowrap") }, "See Jobs →"))
      : null;
    const ticks = h("div", { style: s("display:flex;flex-wrap:wrap;gap:9px 18px;font-size:13px;font-weight:700;color:var(--ink)") },
      ["100% free", "No sign-up to apply", "Real employers"].map((t, i) => h("span", { key: i, style: s("display:inline-flex;align-items:center;gap:5px") }, raw(TICK), t)));
    const copy = h("div", { style: s("display:grid;gap:15px;align-content:center") },
      payPill,
      h("h1", { style: s("margin:0;font-family:var(--font-display);font-weight:800;font-size:" + (wide ? "44px" : "31px") + ";line-height:1.04;letter-spacing:-0.015em;color:var(--ink)") }, CONTENT.h1),
      h("div", { style: s("font-size:" + (wide ? "17.5px" : "15.5px") + ";line-height:1.5;color:var(--ink-muted);text-wrap:pretty;max-width:36ch") }, CONTENT.heroSub),
      ticks,
      countLine);
    const form = h("div", { style: s("width:100%;max-width:" + (wide ? "430px" : "520px") + ";justify-self:" + (wide ? "end" : "center")) }, this.renderHeroForm());
    return h("section", { style: s("flex:none;background:linear-gradient(180deg,var(--fact) 0%,var(--surface) 60%);border-bottom:2px solid var(--ink)") },
      h("div", { style: s("max-width:1060px;margin:0 auto;box-sizing:border-box;padding:" + (wide ? "48px 24px 54px" : "24px 16px 30px") + ";display:grid;gap:" + (wide ? "48px" : "22px") + ";" + (wide ? "grid-template-columns:1.05fr 430px;align-items:center" : "grid-template-columns:1fr")) },
        copy, form));
  }

  // ── recent jobs ───────────────────────────────────────────
  renderRecent(){
    const jobs = (this.data.recent || []).map((r) => this.shape(r));
    if (!jobs.length) return null;
    return h("section", { style: s("display:grid;gap:" + GAP_BLOCK) },
      h("h2", { style: s(sectionH2) }, "Recent " + CONTENT.categoryNoun + " jobs"),
      h("div", { role: "list", style: s("display:grid;grid-template-columns:repeat(auto-fit,minmax(min(320px,100%),1fr));gap:12px") },
        jobs.map((job) => h(Pressable, { key: job.id, tag: "div",
            styleFor: (pd) => s("display:flex;background:var(--surface-raised);border:1px solid var(--ink);border-radius:3px;transition:transform 45ms ease-out,box-shadow 45ms ease-out;"
              + (pd ? "transform:translate(4px,4px);box-shadow:0 0 0 0 var(--ink)" : "box-shadow:4px 4px 0 0 var(--ink)")) },
          h("div", { style: s("flex:1;min-width:0") }, h(JobCard, { job, flush: true }))))),
      this.data.count ? h("a", { href: withUtm(CONTENT.listingPath), style: s("justify-self:start;min-height:44px;display:inline-flex;align-items:center;font-size:14px;font-weight:800;text-transform:uppercase;letter-spacing:0.03em;color:var(--accent)") }, "See all " + this.data.count.toLocaleString() + " " + CONTENT.categoryNoun + " jobs") : null);
  }

  // ── info block ────────────────────────────────────────────
  para(txt){ return h("p", { style: s("margin:0;font-size:15.5px;line-height:1.6;color:var(--ink);text-wrap:pretty") }, txt); }
  subH(txt){ return h("h3", { style: s("margin:0;font-family:var(--font-display);font-weight:800;font-size:17px;line-height:1.25;color:var(--ink)") }, txt); }

  renderPayTable(){
    const info = CONTENT.info;
    return h("div", { style: s("display:grid;gap:8px") },
      info.payTable.map(([label, val, note], i) => h("div", { key: i, style: s("display:grid;grid-template-columns:1fr;gap:2px;padding:10px 0;border-top:1px solid var(--line)") },
        h("div", { style: s("font-size:14px;font-weight:700;color:var(--ink)") }, label),
        h("div", { style: s("font-size:15px;color:var(--ink)") }, val),
        note ? h("div", { style: s("font-size:12.5px;color:var(--ink-muted)") }, note) : null)));
  }

  // Optional credential / rights subsection (Food Worker Card, security guard license, forklift +
  // quota law). A flexible list of `parts`, each a typed tuple, so each trade renders what it needs:
  //   ["para", text] | ["para", boldLead, text]      — paragraph, optional bold lead-in
  //   ["steps", intro, [[title, body], …]]           — numbered process
  //   ["bullets", [ "text" | [label, body], … ]]     — checkmark list (plain or label:value)
  //   ["callout", boldLead|null, body]               — emphasized fact box
  renderCredential(cr){
    return h("div", { style: s("display:grid;gap:12px") },
      this.subH(cr.heading),
      cr.parts.map((p, i) => this.credentialPart(p, i)));
  }
  credentialPart(p, key){
    const type = p[0];
    if (type === "para") {
      const lead = p.length > 2 ? p[1] : null, text = p.length > 2 ? p[2] : p[1];
      return h("p", { key, style: s("margin:0;font-size:15.5px;line-height:1.6;color:var(--ink);text-wrap:pretty") }, lead ? h("strong", null, lead + " ") : null, text);
    }
    if (type === "steps") {
      const intro = p[1], items = p[2];
      return h("div", { key, style: s("display:grid;gap:8px") },
        intro ? this.para(intro) : null,
        h("ol", { style: s("margin:0;padding:0;list-style:none;display:grid;gap:8px;counter-reset:step") },
          items.map(([t, b], i) => h("li", { key: i, style: s("display:flex;gap:10px;align-items:flex-start") },
            h("span", { "aria-hidden": "true", style: s("flex:none;width:22px;height:22px;border-radius:50%;background:var(--ink);color:var(--surface);display:grid;place-items:center;font-size:12px;font-weight:800") }, String(i + 1)),
            h("div", { style: s("font-size:15px;line-height:1.55;color:var(--ink);text-wrap:pretty") }, h("strong", null, t), " " + b)))));
    }
    if (type === "bullets") {
      return h("ul", { key, style: s("margin:0;padding:0;list-style:none;display:grid;gap:7px") },
        p[1].map((it, i) => h("li", { key: i, style: s("display:flex;gap:9px;align-items:flex-start") },
          h("span", { "aria-hidden": "true", style: s("flex:none;margin-top:5px;width:16px;height:16px;border-radius:3px;background:var(--mark);display:grid;place-items:center") }, raw(ROW_CHECK)),
          h("div", { style: s("font-size:15.5px;line-height:1.55;color:var(--ink);text-wrap:pretty") }, Array.isArray(it) ? [h("strong", { key: "l" }, it[0]), " " + it[1]] : it))));
    }
    if (type === "callout") {
      return h("div", { key, style: s("padding:12px 14px;background:var(--fact);border:1px solid var(--ink);border-radius:3px;font-size:14.5px;line-height:1.55;color:var(--fact-ink);text-wrap:pretty") }, p[1] ? h("strong", null, p[1] + " ") : null, p[2]);
    }
    return null;
  }

  renderWhosHiring(){
    const info = CONTENT.info;
    const hiring = this.data.whosHiring || [];
    const seasonal = this.data.seasonalCount || 0;
    return h("div", { style: s("display:grid;gap:10px") },
      this.subH(info.whosHiringHeading),
      hiring.length
        ? h("div", { style: s("display:grid;gap:8px") },
            hiring.map((e, i) => h("a", { key: i, href: withUtm(e.href), className: "hv-bg-sunk", style: s("display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 12px;border:1px solid var(--line);border-radius:3px;text-decoration:none") },
              h("span", { style: s("font-size:15px;font-weight:700;color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap") }, e.company),
              h("span", { style: s("flex:none;font-size:13px;font-weight:700;color:var(--accent)") }, e.count.toLocaleString() + (e.count === 1 ? " job" : " jobs")))))
        : this.para(info.whosHiringFallback),
      info.seasonalNote ? this.para(info.seasonalNote + (seasonal ? " " + seasonal.toLocaleString() + " seasonal " + (seasonal === 1 ? "role is" : "roles are") + " open right now." : "")) : null);
  }

  renderList(heading, intro, rows, note){
    return h("div", { style: s("display:grid;gap:10px") },
      this.subH(heading),
      intro ? this.para(intro) : null,
      h("ol", { style: s("margin:0;padding:0;list-style:none;display:grid;gap:10px;counter-reset:step") },
        rows.map(([lead, body], i) => h("li", { key: i, style: s("display:flex;gap:10px;align-items:flex-start") },
          h("span", { "aria-hidden": "true", style: s("flex:none;width:24px;height:24px;border-radius:50%;background:var(--ink);color:var(--surface);display:grid;place-items:center;font-size:13px;font-weight:800") }, String(i + 1)),
          h("div", { style: s("font-size:15.5px;line-height:1.55;color:var(--ink);text-wrap:pretty") }, h("strong", null, lead), " " + body)))),
      note ? this.para(note) : null);
  }

  renderTips(){
    const info = CONTENT.info;
    return h("div", { style: s("display:grid;gap:10px") },
      this.subH(info.tipsHeading),
      h("ul", { style: s("margin:0;padding:0;list-style:none;display:grid;gap:8px") },
        info.tips.map(([lead, body], i) => h("li", { key: i, style: s("display:flex;gap:9px;align-items:flex-start") },
          h("span", { "aria-hidden": "true", style: s("flex:none;margin-top:5px;width:16px;height:16px;border-radius:3px;background:var(--mark);display:grid;place-items:center") }, raw(ROW_CHECK)),
          h("div", { style: s("font-size:15.5px;line-height:1.55;color:var(--ink);text-wrap:pretty") }, h("strong", null, lead), " " + body)))));
  }

  renderLeads(){
    const info = CONTENT.info;
    return h("div", { style: s("display:grid;gap:10px") },
      this.subH(info.leadsHeading),
      info.leadsIntro ? this.para(info.leadsIntro) : null,
      (info.leadsPaths || []).map((path, pi) => h("div", { key: "p" + pi, style: s("display:flex;flex-wrap:wrap;align-items:center;gap:8px") },
        path.map((step, i) => [
          i ? h("span", { key: "a" + i, "aria-hidden": "true", style: s("display:inline-flex") }, raw(ARROW)) : null,
          h("span", { key: "s" + i, style: s("padding:6px 11px;border:1px solid var(--ink);border-radius:3px;background:var(--surface-raised);font-size:13.5px;font-weight:700;color:var(--ink)") }, step),
        ]))),
      info.leadsNote ? this.para(info.leadsNote) : null);
  }

  renderInfo(){
    const info = CONTENT.info;
    return h("section", { style: s("display:grid;gap:" + GAP_SUB) },
      h("h2", { style: s(sectionH2) }, info.heading),
      // What the work is
      this.para(info.whatTheWork),
      // Optional credential subsection (e.g. the Food Worker Card)
      info.credential ? this.renderCredential(info.credential) : null,
      // Pay
      h("div", { style: s("display:grid;gap:10px") },
        this.subH(info.payHeading),
        info.payIntro ? this.para(info.payIntro) : null,
        this.renderPayTable(),
        info.payPartTime ? this.para(info.payPartTime) : null,
        h("div", { style: s("padding:12px 14px;background:var(--fact);border:1px solid var(--ink);border-radius:3px;font-size:14.5px;line-height:1.55;color:var(--fact-ink);text-wrap:pretty") }, h("strong", null, "Why you can see the pay: "), info.payWhy)),
      // Who's hiring + seasonal
      this.renderWhosHiring(),
      // How hiring works
      this.renderList(info.stepsHeading, info.stepsIntro, info.steps, info.stepsNote),
      // Tips
      this.renderTips(),
      // Where retail can lead
      this.renderLeads());
  }

  // ── why NoProbJobs ────────────────────────────────────────
  renderValueProps(){
    const items = CONTENT.valueProps;
    const grid = this.state.wide ? "repeat(auto-fit,minmax(min(320px,100%),1fr))" : "1fr";
    return h("section", { style: s("margin:0 -14px;padding:16px 14px;background:var(--ink);display:grid;gap:14px") },
      h("h2", { style: s("margin:0;font-family:var(--font-display);font-weight:800;font-size:16px;letter-spacing:0.04em;text-transform:uppercase;color:var(--mark)") }, "Why No Prob Jobs"),
      h("div", { style: s("display:grid;grid-template-columns:" + grid + ";gap:10px 20px") },
        items.map(([t, b], i) => h("div", { key: i, style: s("display:flex;gap:10px;align-items:flex-start") },
          h("span", { "aria-hidden": "true", style: s("flex:none;width:32px;height:32px;border-radius:3px;background:var(--mark);display:grid;place-items:center") }, raw(VP_CHECK)),
          h("div", { style: s("display:grid;gap:3px;min-width:0") },
            h("div", { style: s("font-size:16px;font-weight:700;color:var(--surface)") }, t),
            h("div", { style: s("font-size:15px;line-height:1.35;color:var(--line);text-wrap:pretty") }, b))))));
  }

  renderSecondSignup(){
    return h("section", { style: s("margin:0 -14px;padding:18px 14px;background:var(--mark);display:grid;gap:12px;justify-items:center;text-align:center") },
      h("div", { style: s("font-family:var(--font-display);font-weight:800;font-size:18px;line-height:1.25;color:var(--mark-ink)") }, CONTENT.secondSignupHeading),
      h(Pressable, { tag: "button", onClick: this.scrollToForm, className: "hv-underline-none",
          styleFor: (pd) => s("min-height:48px;display:inline-flex;align-items:center;padding:0 24px;border:0;background:var(--accent);font-size:15px;font-weight:800;text-transform:uppercase;letter-spacing:0.04em;color:var(--accent-ink);cursor:pointer;white-space:nowrap;transition:box-shadow 40ms ease-out,transform 40ms ease-out;box-shadow:"
            + (pd ? "inset -3px -3px 0 0 var(--accent-lite),inset 3px 3px 0 0 var(--accent-dark);transform:translate(1px,1px)" : "inset 3px 3px 0 0 var(--accent-lite),inset -3px -3px 0 0 var(--accent-dark)")) }, CONTENT.formButton));
  }

  // ── browse other work types ───────────────────────────────
  renderBrowse(){
    const cards = (this.data.otherCats || []).filter((c) => c.label !== CONTENT.category);
    const cols = this.state.wide ? "repeat(3,1fr)" : "1fr 1fr";
    return h("section", { style: s("display:grid;gap:" + GAP_BLOCK) },
      h("h2", { style: s(sectionH2) }, "Browse other work types"),
      cards.length ? h("div", { style: s("display:grid;grid-template-columns:" + cols + ";grid-auto-rows:1fr;gap:12px") },
        cards.map((c, i) => h("div", { key: i, style: s("position:relative") },
          h("span", { "aria-hidden": "true", style: s("position:absolute;inset:0;transform:translate(4px,4px);background:var(--mark);border:2px solid var(--ink);border-radius:3px") }),
          h(Pressable, { tag: "a", href: withUtm(c.href), className: "hv-bg-fact",
              styleFor: (pd) => s("position:relative;height:100%;box-sizing:border-box;display:grid;align-content:start;gap:7px;min-height:66px;padding:14px;background:var(--surface-raised);border:2px solid var(--ink);border-radius:3px;text-decoration:none;transition:transform 45ms ease-out;" + (pd ? "transform:translate(4px,4px)" : "")) },
            raw(catIconSvg(c.label, 24)),
            h("div", { style: s("display:grid;gap:2px") },
              h("span", { style: s("font-family:var(--font-display);font-weight:800;font-size:16px;line-height:1.2;color:var(--ink);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:38px") }, c.displayLabel || c.label),
              h("span", { style: s("font-size:13px;line-height:1.35;font-weight:700;color:var(--accent);min-height:18px") }, c.count ? (c.count.toLocaleString() + (c.count === 1 ? " job" : " jobs")) : "")))))) : null,
      h("a", { href: withUtm("/" + CONTENT.marketSlug + "/"), style: s("justify-self:start;min-height:44px;display:inline-flex;align-items:center;font-size:14px;font-weight:800;text-transform:uppercase;letter-spacing:0.03em;color:var(--accent)") }, "Browse all jobs"));
  }

  // ── FAQ (+ FAQPage JSON-LD) ───────────────────────────────
  faqSchema(){
    return {
      "@context": "https://schema.org",
      "@type": "FAQPage",
      "mainEntity": CONTENT.faq.map(([q, a]) => ({ "@type": "Question", "name": q, "acceptedAnswer": { "@type": "Answer", "text": a } })),
    };
  }
  renderFaq(){
    return h("section", { style: s("display:grid;gap:" + GAP_BLOCK) },
      h("h2", { style: s(sectionH2) }, CONTENT.faqHeading),
      h("div", { style: s("display:grid;gap:12px") },
        CONTENT.faq.map(([q, a], i) => h("div", { key: i, style: s("display:grid;gap:4px;padding-bottom:12px;border-bottom:1px solid var(--line)") },
          h("div", { style: s("font-size:16px;font-weight:700;color:var(--ink)") }, q),
          h("div", { style: s("font-size:15px;line-height:1.55;color:var(--ink-muted);text-wrap:pretty") }, a)))),
      // JSON-LD baked into the DOM (search engines read it anywhere in the document).
      h("script", { type: "application/ld+json", dangerouslySetInnerHTML: { __html: JSON.stringify(this.faqSchema()) } }));
  }

  renderFooter(){ return siteFooter(CONTENT.marketSlug); }

  render(){
    return h("div", { className: "landing-scope", style: s("position:relative;display:flex;flex-direction:column;min-height:100%;background:var(--surface)") },
      h(Header, { productName: PRODUCT, alertsInHeader: false }),
      this.renderHero(),
      h("main", { style: s("flex:1;max-width:" + RAIL + ";width:100%;margin:0 auto;box-sizing:border-box;padding:38px 16px 44px;display:grid;gap:" + GAP_SECTION + ";align-content:start") },
        this.renderRecent(),
        this.renderInfo(),
        this.renderFaq(),
        this.renderValueProps(),
        this.renderSecondSignup(),
        this.renderBrowse()),
      this.renderFooter());
  }
}

const sectionH2 = "margin:0 0 3px;font-family:var(--font-display);font-weight:800;font-size:19px;line-height:1.2;letter-spacing:0.01em;color:var(--ink);padding-bottom:10px;border-bottom:2px solid var(--mark)";

const mount = (data) => {
  const root = window.ReactDOM.createRoot(document.getElementById("root"));
  root.render(h(AlertsApp, { data }));
};
const mountIndex = (data) => {
  const root = window.ReactDOM.createRoot(document.getElementById("root"));
  root.render(h(AlertsIndex, { data }));
};

// Shared site footer (guide pages + the index). Market-aware: the "… job guides" link points at the
// current page's market index (marketIndexPath); pass null to omit it (e.g. a marketless surface).
const footerLink = "min-height:44px;display:inline-flex;align-items:center;font-size:13px;font-weight:600;color:var(--line)";
function siteFooter(marketSlug){
  const mk = marketSlug ? marketBySlug(marketSlug) : null;
  return h("footer", { style: s("flex:none;background:var(--ink)") },
    h("div", { style: s("max-width:" + RAIL + ";margin:0 auto;box-sizing:border-box;padding:16px 14px;display:grid;justify-items:center;gap:8px") },
      h("div", { style: s("font-size:14px;font-weight:600;color:var(--line);text-align:center") }, "Free for job seekers. No signup required to apply."),
      h("div", { style: s("display:flex;flex-wrap:wrap;justify-content:center;gap:4px 20px") },
        marketSlug ? h("a", { key: "g", href: marketIndexPath(marketSlug), style: s(footerLink) }, (mk ? mk.name : "Washington") + " job guides") : null,
        h("a", { key: "p", href: RT.PRIVACY_URL, target: "_blank", rel: "noopener noreferrer", style: s(footerLink) }, "Privacy Policy"))));
}

// The per-market index hub (/alerts/{market}/): a guides grid with live counts. Renders from the
// index blob (kind:"index") that boot() detects — no signup form, it's a navigation/SEO hub.
function AlertsIndex(props){
  const d = props.data || { marketName: "Washington", marketSlug: "washington", guides: [] };
  const wide = window.matchMedia(BP).matches;
  const guides = d.guides || [];
  const total = guides.reduce((sum, g) => sum + (g.count || 0), 0);
  return h("div", { className: "landing-scope", style: s("position:relative;display:flex;flex-direction:column;min-height:100%;background:var(--surface)") },
    h(Header, { productName: PRODUCT, alertsInHeader: false }),
    h("section", { style: s("flex:none;background:linear-gradient(180deg,var(--fact) 0%,var(--surface) 72%);border-bottom:2px solid var(--ink)") },
      h("div", { style: s("max-width:" + RAIL + ";margin:0 auto;box-sizing:border-box;padding:" + (wide ? "40px 24px 30px" : "26px 16px 22px") + ";display:grid;gap:12px;justify-items:start") },
        h("h1", { style: s("margin:0;font-family:var(--font-display);font-weight:800;font-size:" + (wide ? "38px" : "27px") + ";line-height:1.08;letter-spacing:-0.01em;color:var(--ink)") }, d.marketName + " job guides"),
        h("div", { style: s("font-size:16px;line-height:1.5;color:var(--ink-muted);text-wrap:pretty;max-width:46ch") }, "No-experience jobs in " + d.marketName + " by work type — what the work is, what it pays, how hiring works, and free alerts for each."),
        total ? h("div", { style: s("font-size:14px;font-weight:800;color:var(--accent)") }, total.toLocaleString() + " no-experience jobs hiring right now") : null)),
    h("main", { style: s("flex:1;max-width:" + RAIL + ";width:100%;margin:0 auto;box-sizing:border-box;padding:32px 16px 40px;display:grid;align-content:start") },
      h("div", { style: s("display:grid;grid-template-columns:" + (wide ? "repeat(3,1fr)" : "1fr 1fr") + ";grid-auto-rows:1fr;gap:12px") },
        guides.map((g, i) => h("div", { key: i, style: s("position:relative") },
          h("span", { "aria-hidden": "true", style: s("position:absolute;inset:0;transform:translate(4px,4px);background:var(--mark);border:2px solid var(--ink);border-radius:3px") }),
          h(Pressable, { tag: "a", href: g.path, className: "hv-bg-fact",
              styleFor: (pd) => s("position:relative;height:100%;box-sizing:border-box;display:grid;align-content:start;gap:8px;min-height:104px;padding:15px;background:var(--surface-raised);border:2px solid var(--ink);border-radius:3px;text-decoration:none;transition:transform 45ms ease-out;" + (pd ? "transform:translate(4px,4px)" : "")) },
            g.iconCat ? raw(catIconSvg(g.iconCat, 26)) : h("span", { style: s("display:block;height:26px") }),
            h("div", { style: s("font-family:var(--font-display);font-weight:800;font-size:16px;line-height:1.2;color:var(--ink)") }, g.label),
            h("div", { style: s("font-size:13px;font-weight:700;color:var(--accent)") }, g.count ? (g.count.toLocaleString() + " jobs hiring") : "Set an alert"),
            h("div", { style: s("font-size:13px;font-weight:700;color:var(--ink-muted)") }, "View guide →")))))),
    siteFooter(d.marketSlug));
}
// Data ships INLINE (baked by prerender/build.mjs) — no client query. Set today from the baked
// pulledAt before first render, then mount. Fall back to an empty scaffold if the blob is missing.
// Pick the page's content from the URL: /alerts/{market}/{category-slug}/ -> PAGES[slug].
// Runs before mount() so the component constructs against the right CONTENT.
function selectPage(){
  try {
    const m = (window.location.pathname || "").match(/\/alerts\/[^/]+\/([^/]+)/);
    if (m && PAGES[m[1]]) { CONTENT = PAGES[m[1]]; return; }
  } catch (e) {}
  CONTENT = PAGES.retail;
}
// Index blob (kind:"index") -> the hub; otherwise a guide page: pick CONTENT from the path, then
// mount from the inline slice. Empty guide scaffold only if the blob is missing (un-baked shell).
const boot = () => {
  const el = document.getElementById("__npj_data");
  if (el) {
    try {
      const d = JSON.parse(el.textContent);
      if (d.pulledAt) R.setToday(d.pulledAt);
      if (d.kind === "index") { mountIndex(d); return; }
      selectPage();
      mount(d);
      return;
    } catch (e) { /* malformed blob -> render empty guide scaffold */ }
  }
  selectPage();
  mount({ count: 0, maxPay: null, recent: [], otherCats: [], whosHiring: [], seasonalCount: 0, pulledAt: null });
};
boot();
