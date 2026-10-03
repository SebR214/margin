/* The receipt replay (SEB-57 / R2 / SEB-173 / SEB-178 / SEB-186).
 *
 * Every published index/country number is clickable. Clicking one fetches
 * data/receipts/<CCY>.json (built by tools/emit_receipts.py, SEB-56) and
 * replays it as four steps: the evidence, the official rate, the math, the
 * verdict. Nothing here recomputes or reformats the number that was clicked --
 * the exact text the reader saw travels in via data-receipt-value and is
 * echoed back verbatim, so the overlay cannot disagree with the page it was
 * opened from.
 *
 * corridor.html's own cost-in-bps figures (SEB-178) replay the same way, from
 * data/corridor_receipts/<corridor>_<notional>_<hour>.json (built by
 * tools/emit_corridor_receipts.py), and sending-money.html's own
 * provider-ranking cost figures (SEB-186) replay the same way too, from
 * data/provider_receipts/<corridor>_<size>_<hour>.json (built by
 * tools/emit_provider_receipts.py) -- the same four-step SHELL (the dialog,
 * the numbered steps, the timers, the raw-file footer) rendered by the same
 * render()/open-close machinery below, just fed a differently-shaped receipt
 * and their own set of copy.json templates (copy.json's "receiptCorridor"
 * and "receiptProvider" keys) rather than a second component. See
 * buildProviderSteps()'s own comment for why a wired row's math always
 * matches the comparison figure the page itself is showing, never the
 * provider's own number underneath it.
 *
 * sending-money.html's price-change list (SEB-187) replays the same shell
 * again, from data/pricechange_receipts/<key>.json (built by
 * tools/emit_pricechange_receipts.py) and copy.json's "receiptPriceChange"
 * templates -- see buildPriceChangeSteps().
 *
 * Wired once, on document, by delegation -- so it survives a full re-render
 * of index.html's innerHTML-driven sections as well as a plain DOM page
 * (country.html, countries.html, corridor.html, sending-money.html), the
 * same reason index.html already delegates its own search box.
 *
 * Paths below (copy.json, data/receipts/<CCY>.json,
 * data/corridor_receipts/....json, data/provider_receipts/....json, and
 * every source file a step links to)
 * are resolved against the HOST PAGE, not this script's own location in
 * js/ -- every page that includes this file lives at the repo root alongside
 * copy.json and data/, same as every other fetch those pages already make.
 *
 * copy.json is fetched by this file directly, rather than relying on the
 * host page to have already loaded it, since not every page that shows a
 * published number also loads the copy deck today. A missing or broken
 * copy.json renders blank labels here, same rule as every other page: never
 * a made-up fallback string.
 *
 * Stdlib DOM only, no build step, matching every other script on this site.
 */
(function () {
  "use strict";

  var copyDocPromise = null;
  function getCopyDoc() {
    if (!copyDocPromise) {
      copyDocPromise = fetch("copy.json", { cache: "no-store" })
        .then(function (r) { return r.ok ? r.json() : {}; })
        .catch(function () { return {}; });
    }
    return copyDocPromise;
  }
  function getCopy() {
    return getCopyDoc().then(function (c) { return (c && c.receipt) || {}; });
  }
  function getCorridorCopy() {
    return getCopyDoc().then(function (c) { return (c && c.receiptCorridor) || {}; });
  }
  function getCrossoverCopy() {
    return getCopyDoc().then(function (c) { return (c && c.receiptCrossover) || {}; });
  }
  function getPriceChangeCopy() {
    return getCopyDoc().then(function (c) { return (c && c.receiptPriceChange) || {}; });
  }
  function getMeterCopy() {
    return getCopyDoc().then(function (c) { return (c && c.receiptMeter) || {}; });
  }
  function getProviderCopy() {
    return getCopyDoc().then(function (c) { return (c && c.receiptProvider) || {}; });
  }

  function T(s, vals) {
    if (!s) return "";
    return s.replace(/\{(\w+)\}/g, function (_, k) {
      return vals && vals[k] != null ? vals[k] : "";
    });
  }

  function fmtNum(v) {
    return v === null || v === undefined || !isFinite(v) ? "—"
      : Number(v).toLocaleString("en-US", { maximumFractionDigits: 6 });
  }

  // Same tiered precision as sending-money.html's own r.cost_pct.toFixed(2) --
  // more decimal places for a smaller number so a real cost like 0.04% never
  // prints as 0.00%, which would read as "not measured".
  function fmtPct(v) {
    if (v === null || v === undefined || !isFinite(v)) return "—";
    var a = Math.abs(v), dp = a >= 10 ? 1 : a >= 0.1 ? 2 : 3;
    return v.toFixed(dp) + "%";
  }

  function fmtWhen(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    return isNaN(d.getTime()) ? iso : d.toISOString().slice(0, 16).replace("T", " ") + " UTC";
  }

  // "2026-09-27" -> "27 Sep" -- same no-year, same-window convention
  // sending-money.html's own fmtDay() uses for these dates.
  var MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  function fmtDay(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
    return m ? (String(+m[3]) + " " + MONTHS[+m[2] - 1]) : (iso || "—");
  }

  // A meter receipt's streak boundary ({date, hour}) as "YYYY-MM-DD HH:00" --
  // not an ISO string, since the boundary is a whole UTC hour tools/
  // emit_meter_receipts.py already split into those two fields, not a single
  // timestamp to re-parse.
  function fmtHour(b) {
    if (!b || b.date == null || b.hour == null) return "—";
    return b.date + " " + String(b.hour).padStart(2, "0") + ":00";
  }

  // Mirrors emit_countries.py's evidence_words() -- word choice only, not the
  // index arithmetic, the same kind of small presentational duplication
  // chart.js already carries for chart.py's geometry.
  function evidenceCountWords(kind, n) {
    n = n || 0;
    if (kind === "order_book_median" || kind === "order_book_single")
      return n + " order book" + (n === 1 ? "" : "s");
    if (kind === "broker_median" || kind === "broker_single")
      return n + " broker quote" + (n === 1 ? "" : "s");
    if (kind === "p2p_buy_median")
      return n === 1 ? "1 person selling" : n + " people selling";
    if (kind === "p2p_fallback") return "an independent price check";
    return null;
  }

  // Every step names the real file it came from, derived from the receipt's
  // own source_files list -- never a second, invented path.
  function stepFiles(r) {
    var rateFile = r.official_rate && r.official_rate.source_file;
    var files = r.source_files || [];
    var countryFile = files.filter(function (f) { return f.indexOf("data/countries/") === 0; })[0];
    var evidenceFiles = files.filter(function (f) { return f !== rateFile && f !== countryFile; });
    var verdictFile = evidenceFiles.filter(function (f) { return f.indexOf("p2p_sides") >= 0; })[0]
      || evidenceFiles[0] || countryFile;
    return {
      evidence: evidenceFiles.length ? evidenceFiles : (countryFile ? [countryFile] : []),
      rate: rateFile ? [rateFile] : [],
      math: countryFile ? [countryFile] : [],
      verdict: verdictFile ? [verdictFile] : []
    };
  }

  // The only two `evidence_rule.reason_code` values a not-applicable rule can
  // carry, each mapped to its own copy.json sentence -- never the rule's own
  // internal note, so nothing but reviewed reader copy ever reaches a page.
  // Mirrored in tools/emit_receipts.py's VERDICT_NOTE_COPY_KEYS.
  var REASON_CODE_COPY_KEYS = {
    order_book: "verdictNoteOrderBook",
    single_source_aggregate: "verdictNoteAggregate"
  };

  function buildSteps(receipt, copy) {
    var files = stepFiles(receipt);
    var ev = receipt.evidence || {}, rate = receipt.official_rate || {},
      comp = receipt.computation || {}, rule = receipt.evidence_rule || {};

    var words = evidenceCountWords(ev.source_kind, ev.n_offers) || ev.source_words || "";
    var evidenceText = T(copy.evidenceSentenceTemplate, {
      words: words, price: fmtNum(ev.buy_median), ccy: receipt.ccy
    });
    var evidenceNote = ev.offer_detail === "per_offer" ? copy.evidenceOffersNote : copy.evidenceAggregateNote;
    var collected = T(copy.evidenceCollectedTemplate, { when: fmtWhen(ev.collected_at) });

    var rateWord = rate.class === "managed" ? copy.rateManaged
      : rate.class === "pegged" ? copy.ratePegged
      : rate.class === "unmaintained" ? copy.rateUnmaintained
      : copy.rateMarket;
    var rateText = T(copy.rateSentenceTemplate, {
      value: fmtNum(rate.value), ccy: receipt.ccy, source: rate.source || ""
    });

    var mathText = T(copy.mathSentenceTemplate, {
      numerator: fmtNum(comp.numerator), ccy: receipt.ccy, denominator: fmtNum(comp.denominator)
    });
    // Always the receipt's own stored result_pct, never the page's own
    // displayed value (data-receipt-value) -- a page can show a different,
    // smoothed figure next to this number (the 24-hour median, say) than
    // what this hour's own receipt computed, and this step is specifically
    // narrating THIS division, so it states only what that division
    // actually produced (SEB-173, caught by the 10-country spot check: the
    // page's displayed figure and computation.result_pct disagreed for most
    // countries once median_24h_pct became the "now" convention).
    var mathResult = T(copy.mathResultTemplate, { result: fmtNum(comp.result_pct) });

    var verdictText, verdictDetail = "";
    if (receipt.published) {
      verdictText = copy.verdictPublished;
      if (rule.applies) {
        verdictDetail = T(copy.verdictRuleDetailTemplate, {
          actual: rule.buy_ads_actual, required: rule.min_buy_ads_required
        });
      } else if (rule.reason_code && REASON_CODE_COPY_KEYS[rule.reason_code]) {
        verdictDetail = copy[REASON_CODE_COPY_KEYS[rule.reason_code]] || "";
      }
    } else {
      verdictText = T(copy.verdictWithheldTemplate, { reason: receipt.not_published_reason || "" });
    }

    return [
      { label: copy.step1Label, text: [evidenceText, evidenceNote, collected].filter(Boolean).join(" "), files: files.evidence },
      { label: copy.step2Label, text: [rateText, rateWord, copy.rateStalenessNote].filter(Boolean).join(" "), files: files.rate },
      { label: copy.step3Label, text: [mathText, mathResult].filter(Boolean).join(" "), files: files.math },
      { label: copy.step4Label, text: [verdictText, verdictDetail].filter(Boolean).join(" "), files: files.verdict }
    ];
  }

  // Same tiered rounding as corridor.html's own pct(): a bps figure (one
  // hundredth of a percent) shown as a percent, with more decimal places
  // for a smaller number so a real cost like 0.004% never prints as 0.00%,
  // which would read as "not measured". bps itself never reaches this text.
  function pctFromBps(b) {
    if (b === null || b === undefined || !isFinite(b)) return "—";
    var p = b / 100, a = Math.abs(p), dp = a >= 10 ? 1 : a >= 0.1 ? 2 : 3;
    return a.toFixed(dp) + "%";
  }

  // fee-tiers.html's crossover receipt (SEB-192) reports amounts in whole
  // currency, not hundredths of a percent, so it gets its own formatter
  // rather than pctFromBps's tiered rounding.
  function fmtSgd(v) {
    return v === null || v === undefined || !isFinite(v) ? "—"
      : "S$" + Math.round(v).toLocaleString("en-US");
  }
  function fmtPct2(v) {
    return v === null || v === undefined || !isFinite(v) ? "—" : Number(v).toFixed(2) + "%";
  }

  // corridor.html's cost-in-bps receipt (SEB-178): the same four-step shell
  // buildSteps() fills for index/country numbers, fed from a differently-
  // shaped receipt (tools/emit_corridor_receipts.py) and copy.json's
  // "receiptCorridor" templates instead of "receipt" -- a corridor's cost
  // has order-book evidence and fee legs, not a single official rate, so
  // step 2 names the fees instead of a rate.
  function buildCorridorSteps(receipt, copy, regime) {
    var ev = receipt.evidence || {}, fees = receipt.fees || {};
    var files = (receipt.source_files || []);
    var on = ev.onramp || {}, off = ev.offramp || {};

    var buyText = T(copy.evidenceBuySentenceTemplate, {
      venue: on.venue_display || on.venue, topPrice: fmtNum(on.top_price), avgPrice: fmtNum(on.average_price_paid),
      ccy: receipt.src_ccy
    });
    var sellText = T(copy.evidenceSellSentenceTemplate, {
      venue: off.venue_display || off.venue, topPrice: fmtNum(off.top_price), avgPrice: fmtNum(off.average_price_received),
      ccy: receipt.dst_ccy
    });
    var collected = T(copy.evidenceCollectedTemplate, { when: fmtWhen(ev.collected_at) });
    var evidenceText = [buyText, sellText, copy.evidenceBookNote, collected].filter(Boolean).join(" ");

    function feeLine(status, label, pctValue) {
      if (status === "not_priced") return T(copy.feeNotPricedTemplate, { label: label });
      if (status === "not_modeled") return T(copy.feeNotModeledTemplate, { label: label });
      if (status === "not_available") return T(copy.feeNotAvailableTemplate, { label: label });
      return T(copy.feeLineTemplate, { label: label, pct: pctFromBps(pctValue) });
    }
    var onFee = fees.onramp || {}, offFee = fees.offramp || {}, net = fees.network || {};
    var dep = fees.deposit || {}, wd = fees.withdrawal || {};
    var onBps = regime === "maker" ? onFee.maker_bps : onFee.taker_bps;
    var offBps = regime === "maker" ? offFee.maker_bps : offFee.taker_bps;
    var feeLines = [
      feeLine("priced", T(copy.onrampFeeLabelTemplate, { venue: onFee.venue_display || onFee.venue }), onBps),
      feeLine("priced", T(copy.offrampFeeLabelTemplate, { venue: offFee.venue_display || offFee.venue }), offBps),
      net.value_stable !== null && net.value_stable !== undefined
        ? T(copy.networkFeeAmountTemplate, { amount: fmtNum(net.value_stable) }) : "",
      feeLine(dep.status, T(copy.depositLabelTemplate, { ccy: receipt.src_ccy, venue: dep.venue_display || dep.venue }), dep.value_bps),
      feeLine(wd.status, copy.withdrawalLabel, wd.value_bps)
    ];
    var feesText = feeLines.filter(Boolean).join(" ");

    var comp = (receipt.computation || {})[regime] || {};
    var mathText = [copy.mathSentence, T(copy.mathResultTemplate, { result: pctFromBps(comp.result_pct) })]
      .filter(Boolean).join(" ");

    var regimeNote = regime === "maker" ? copy.regimeLimit : copy.regimeMarket;
    var noteText = [regimeNote, !comp.legs_available ? copy.noLegsNote : ""].filter(Boolean).join(" ");

    return [
      { label: copy.step1Label, text: evidenceText, files: ["data/samples.csv"] },
      { label: copy.step2Label, text: feesText, files: files },
      { label: copy.step3Label, text: mathText, files: files },
      { label: copy.step4Label, text: noteText, files: files }
    ];
  }

  // fee-tiers.html's volume-tier crossover (SEB-192): same shell again, a
  // receipt keyed by (regime, the fee schedule's own timestamp) instead of
  // currency or corridor, from tools/emit_crossover_receipts.py and copy.json's
  // "receiptCrossover" templates. Unlike a corridor's cost this number is not
  // itself a direct measurement -- it is the real samples re-costed at a
  // hypothetical fee tier, so every step here says "rebuilt", never "measured".
  function buildCrossoverSteps(receipt, copy) {
    var ev = receipt.evidence || {}, ts = receipt.tier_schedule || {},
      recon = receipt.reconstruction || {}, search = receipt.search || {};

    var evidenceText = T(copy.evidenceSentenceTemplate, {
      n: receipt.n_samples, first: fmtWhen(ev.first_ts), last: fmtWhen(ev.last_ts),
      baseline: pctFromBps(receipt.baseline_cost_bps_median)
    });

    var feesText = T(copy.feeSentenceTemplate, {
      volume: fmtSgd(recon.crossover_volume_sgd),
      feeIr: fmtPct2(recon.fee_pct_at_crossover_ir),
      feeCoins: fmtPct2(recon.fee_pct_at_crossover_coins_ph_median)
    });

    var reconText = [copy.reconstructionNote, T(copy.reconstructionSentenceTemplate, {
      result: pctFromBps(recon.reconstructed_cost_bps_median)
    })].filter(Boolean).join(" ");

    var searchText = T(copy.searchSentenceTemplate, {
      lo: fmtSgd(search.lo_volume_sgd), hi: fmtSgd(search.hi_volume_sgd),
      volume: fmtSgd(search.converged_volume_sgd)
    });
    var regimeNote = receipt.regime === "maker" ? copy.regimeLimit : copy.regimeMarket;

    return [
      { label: copy.step1Label, text: evidenceText, files: ["data/samples.csv"] },
      { label: copy.step2Label, text: feesText, files: ["data/fee_tier_schedule.csv"] },
      { label: copy.step3Label, text: reconText, files: receipt.source_files || [] },
      { label: copy.step4Label, text: [searchText, regimeNote].filter(Boolean).join(" "), files: ["data/volume_crossover.json"] }
    ];
  }

  // The fourth receipt shape (SEB-187): a confirmed price change from
  // data/pricechange_receipts/<key>.json, built by
  // tools/emit_pricechange_receipts.py. No official-rate step -- the whole
  // point of the pairwise-unanimity test this explains is that the exchange
  // rate cancels out of the comparison, so this shape never mentions one.
  function buildPriceChangeSteps(receipt, copy) {
    var stored = receipt.stored || {}, comp = receipt.computation || {}, ev = receipt.evidence || {};
    var files = receipt.source_files || [];
    var panelFile = ev.source_file ? [ev.source_file] : [];
    var recordFile = files.filter(function (f) { return f.indexOf("price_changes.csv") >= 0; });
    recordFile = recordFile.length ? recordFile : ["data/price_changes.csv"];

    var up = Number(stored.move_pct) > 0;
    var whatChanged = T(copy.whatChangedTemplate, {
      provider: receipt.provider, direction: up ? copy.directionUpWord : copy.directionDownWord,
      amountWords: receipt.amount_words, routeWords: receipt.route_words,
      oldDay: fmtDay(receipt.old_day), newDay: fmtDay(receipt.day)
    });

    var nOther = comp.per_peer_move_pct ? Object.keys(comp.per_peer_move_pct).length : null;
    var checkSentence = T(copy.checkSentenceTemplate, {
      nAgree: stored.n_agree, nOther: nOther, thresholdPts: fmtNum(comp.threshold_pct)
    });

    var mathSentence = T(copy.mathSentenceTemplate, {
      provider: receipt.provider, newDay: fmtDay(receipt.day), newCostPct: fmtNum(stored.new_cost_pct),
      movePct: fmtNum(stored.move_pct), oldDay: fmtDay(receipt.old_day), oldCostPct: fmtNum(stored.old_cost_pct)
    });
    var mathPrevNote = T(copy.mathPrevNoteTemplate, {
      oldDay: fmtDay(receipt.old_day), prevCostPct: fmtNum(stored.prev_day_cost_pct), oldCostPct: fmtNum(stored.old_cost_pct)
    });

    var verdictText;
    if (receipt.kind === "weekend_up") verdictText = copy.verdictWeekendUpTemplate;
    else if (receipt.kind === "weekend_back") verdictText = copy.verdictWeekendBackTemplate;
    else verdictText = T(copy.verdictChangeTemplate, { provider: receipt.provider });

    return [
      { label: copy.step1Label, text: whatChanged, files: panelFile },
      { label: copy.step2Label, text: [checkSentence, copy.checkNote].filter(Boolean).join(" "), files: panelFile },
      { label: copy.step3Label, text: [mathSentence, mathPrevNote].filter(Boolean).join(" "), files: recordFile },
      { label: copy.step4Label, text: verdictText, files: recordFile }
    ];
  }

  // sending-money.html's provider-ranking cost figures (SEB-186): the same
  // step shell buildSteps() fills for index/country numbers, fed from a
  // differently-shaped receipt (tools/emit_provider_receipts.py) and
  // copy.json's "receiptProvider" templates.
  //
  // `row` is ALREADY the one entry from data/provider_receipts/....json that
  // matches the provider clicked (openProvider() below picks it out of the
  // file's own `rows` list). Its computation.result_pct is, by construction,
  // always the number sending-money.html itself is showing for that row --
  // for a provider with its own published quote AND a public comparison
  // figure, that is the COMPARISON figure, never the provider's own number,
  // because that is which one the page displays (see
  // tools/emit_provider_receipts.py's own docstring, "THE WIRING DECISION").
  // The provider's own quote still appears, in evidence.own_quote, as
  // supporting context underneath -- never as the number this step's math
  // claims to explain.
  function buildProviderSteps(row, copy) {
    var ev = row.evidence || {}, comp = row.computation || {};
    var provider = row.provider, files = row.source_files || [];

    if (!comp) {
      var fallbackText = ev.status === "missing"
        ? T(copy.evidenceMissingTemplate, { provider: provider })
        : copy.evidenceUnavailableTemplate;
      return [{ label: copy.step1Label, text: fallbackText || "", files: files }];
    }

    var evidenceText;
    if (ev.status === "comparison") {
      evidenceText = T(copy.evidenceComparisonSentenceTemplate, { provider: provider, landed: fmtNum(ev.landed) });
      if (ev.own_quote) {
        evidenceText += " " + T(copy.evidenceOwnNoteTemplate, {
          provider: provider, rate: fmtNum(ev.own_quote.rate), fee: fmtNum(ev.own_quote.fee)
        });
      }
    } else {
      evidenceText = T(copy.evidenceOwnSentenceTemplate, {
        provider: provider, rate: fmtNum(ev.rate), fee: fmtNum(ev.fee), received: fmtNum(ev.received)
      });
    }
    var collected = T(copy.evidenceCollectedTemplate, { when: fmtWhen(ev.collected_at) });

    var mathText = [copy.mathSentence, T(copy.mathResultTemplate, { result: fmtPct(comp.result_pct) })]
      .filter(Boolean).join(" ");

    var steps = [
      { label: copy.step1Label, text: [evidenceText, collected].filter(Boolean).join(" "), files: files },
      { label: copy.step2Label, text: mathText, files: files }
    ];
    if (comp.note) steps.push({ label: copy.step3Label, text: comp.note, files: files });
    return steps;
  }

  // how-it-was-built.html's two JSON-backed meter tiles (SEB-190): the same
  // step shell buildSteps() fills for index/country numbers, fed from a
  // differently-shaped receipt per meter (tools/emit_meter_receipts.py) and
  // copy.json's "receiptMeter" templates. One function, not two, because
  // both meters share the same two-step shape (the evidence, the
  // count) -- only the sentence naming that evidence differs per meter.
  function buildMeterSteps(receipt, copy) {
    var files = receipt.source_files || [];
    var when = T(copy.evidenceCollectedTemplate, { when: fmtWhen(receipt.computed_at) });
    var evidenceText = "", countText = "";

    if (receipt.meter === "commits_today") {
      var total = (receipt.entries || []).length;
      evidenceText = T(copy.commitsEvidenceTemplate, {
        total: total, excluded: total - receipt.value, day: receipt.day
      });
      countText = T(copy.commitsCountTemplate, { value: receipt.value });
    } else if (receipt.meter === "unbroken_hours") {
      evidenceText = T(copy.hoursEvidenceTemplate, {
        start: fmtHour(receipt.streak_start), end: fmtHour(receipt.streak_end)
      });
      countText = T(copy.hoursCountTemplate, { value: receipt.value });
    }

    return [
      { label: copy.step1Label, text: [evidenceText, when].filter(Boolean).join(" "), files: files },
      { label: copy.step2Label, text: countText, files: files }
    ];
  }

  var STYLE = [
    ".receipt-overlay{position:fixed;inset:0;z-index:1000;display:flex;align-items:center;justify-content:center;padding:24px;}",
    ".receipt-backdrop{position:absolute;inset:0;background:rgba(32,30,29,.55);}",
    ".receipt-dialog{position:relative;background:#fff;color:#201e1d;max-width:520px;width:100%;max-height:86vh;overflow:auto;",
    "padding:28px 26px 22px;font-family:Archivo,system-ui,sans-serif;box-shadow:0 8px 40px rgba(0,0,0,.25);}",
    ".receipt-close{position:absolute;top:14px;right:14px;appearance:none;border:0;background:transparent;font-size:22px;",
    "line-height:1;cursor:pointer;color:#201e1d;padding:4px 8px;}",
    ".receipt-title{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:#7d7979;margin:0 0 6px;}",
    ".receipt-value{font-weight:800;font-size:32px;line-height:1;margin:0 0 18px;font-variant-numeric:tabular-nums;}",
    ".receipt-steps{list-style:none;margin:0;padding:0;}",
    ".receipt-step{display:grid;grid-template-columns:24px 1fr auto;gap:10px 14px;padding:12px 0;",
    "border-top:1px solid rgba(32,30,29,.15);align-items:start;opacity:0;transform:translateY(6px);}",
    ".receipt-step:first-child{border-top:0;}",
    "@media (prefers-reduced-motion:no-preference){.receipt-step{transition:opacity .3s ease-out,transform .3s ease-out;}}",
    ".receipt-step.is-visible{opacity:1;transform:none;}",
    "@media (prefers-reduced-motion:reduce){.receipt-step{opacity:1;transform:none;}}",
    ".receipt-step-num{width:22px;height:22px;border-radius:50%;background:#201e1d;color:#fff;font-size:11px;",
    "font-weight:800;display:flex;align-items:center;justify-content:center;}",
    ".receipt-step-label{font-weight:800;font-size:13px;margin-bottom:3px;}",
    ".receipt-step-text{font-size:13px;line-height:1.5;color:#201e1d;}",
    ".receipt-step-file{font-size:11px;text-align:right;white-space:nowrap;}",
    ".receipt-step-file a,.receipt-raw-links a{color:#817FCC;text-decoration:none;}",
    ".receipt-step-file a:hover,.receipt-raw-links a:hover{text-decoration:underline;}",
    ".receipt-footer{border-top:2px solid #201e1d;margin-top:6px;padding-top:12px;}",
    ".receipt-raw-label{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#7d7979;margin-bottom:6px;}",
    ".receipt-raw-links{font-size:12px;line-height:1.8;}",
    ".receipt-loading{font-size:13px;color:#7d7979;padding:12px 0;}",
    "[data-receipt-ccy],[data-receipt-corridor-file],[data-receipt-crossover-file],[data-receipt-provider-file],[data-pricechange-key],[data-receipt-meter-file]{cursor:pointer;}"
  ].join("\n");

  function ensureStyle() {
    if (document.getElementById("receipt-style")) return;
    var s = document.createElement("style");
    s.id = "receipt-style";
    s.textContent = STYLE;
    document.head.appendChild(s);
  }

  function escAttr(s) { return String(s == null ? "" : s).replace(/"/g, "&quot;"); }
  function escHtml(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function fileLink(path) {
    var a = document.createElement("a");
    a.href = path;
    a.textContent = path;
    return a;
  }

  var overlayEl = null, lastFocus = null, timers = [];

  function clearTimers() {
    timers.forEach(function (t) { clearTimeout(t); });
    timers = [];
  }

  function close() {
    if (!overlayEl) return;
    clearTimers();
    overlayEl.remove();
    overlayEl = null;
    document.removeEventListener("keydown", onKeydown, true);
    if (lastFocus && lastFocus.focus) lastFocus.focus();
    lastFocus = null;
  }

  function onKeydown(e) {
    if (e.key === "Escape") close();
  }

  // The shared shell every receipt kind paints into: the numbered steps list
  // and the raw-file footer. Takes already-built steps (label/text/files)
  // rather than a receipt, so it has no opinion on what shape of receipt
  // produced them -- buildSteps() (index/country), buildCorridorSteps()
  // (corridor.html), buildCrossoverSteps() (fee-tiers.html),
  // buildProviderSteps() and buildPriceChangeSteps() (sending-money.html)
  // are the only places that know that.
  function paintSteps(steps, sourceFiles, rawFilesLabel) {
    if (!overlayEl) return;
    var ol = overlayEl.querySelector(".receipt-steps");
    ol.innerHTML = "";
    var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    steps.forEach(function (step, i) {
      var li = document.createElement("li");
      li.className = "receipt-step";
      var num = document.createElement("div");
      num.className = "receipt-step-num";
      num.textContent = String(i + 1);
      var body = document.createElement("div");
      body.className = "receipt-step-body";
      var label = document.createElement("div");
      label.className = "receipt-step-label";
      label.textContent = step.label || "";
      var text = document.createElement("div");
      text.className = "receipt-step-text";
      text.textContent = step.text || "";
      body.appendChild(label);
      body.appendChild(text);
      var fileCol = document.createElement("div");
      fileCol.className = "receipt-step-file";
      (step.files || []).forEach(function (f, j) {
        if (j) fileCol.appendChild(document.createElement("br"));
        fileCol.appendChild(fileLink(f));
      });
      li.appendChild(num);
      li.appendChild(body);
      li.appendChild(fileCol);
      ol.appendChild(li);
      if (reduced) {
        li.classList.add("is-visible");
      } else {
        timers.push(setTimeout(function () { li.classList.add("is-visible"); }, i * 750));
      }
    });

    var rawLabel = overlayEl.querySelector(".receipt-raw-label");
    rawLabel.textContent = rawFilesLabel || "";
    var rawLinks = overlayEl.querySelector(".receipt-raw-links");
    rawLinks.innerHTML = "";
    (sourceFiles || []).forEach(function (f, j) {
      if (j) rawLinks.appendChild(document.createTextNode(" · "));
      rawLinks.appendChild(fileLink(f));
    });
  }

  function render(receipt, copy) {
    paintSteps(buildSteps(receipt, copy), receipt.source_files, copy.rawFilesLabel);
  }

  function renderLoading(copy) {
    if (!overlayEl) return;
    overlayEl.querySelector(".receipt-steps").innerHTML =
      '<li class="receipt-loading is-visible">' + escHtml(copy.loadingLabel || "") + "</li>";
  }

  function renderError(copy, file) {
    if (!overlayEl) return;
    overlayEl.querySelector(".receipt-steps").innerHTML =
      '<li class="receipt-loading is-visible">'
      + escHtml(T(copy.loadErrorTemplate, { file: file })) + "</li>";
  }

  // Builds the dialog shell common to every receipt kind and wires its
  // close behaviour -- what every receipt, index/country, corridor,
  // crossover, provider or price-change, shares. Returns the close button so the
  // caller can finish wiring its own copy-specific title/aria-label once
  // copy.json resolves.
  function openShell(ariaLabel, displayValue, triggerEl) {
    ensureStyle();
    lastFocus = triggerEl;
    overlayEl = document.createElement("div");
    overlayEl.className = "receipt-overlay";
    overlayEl.innerHTML =
      '<div class="receipt-backdrop"></div>'
      + '<div class="receipt-dialog" role="dialog" aria-modal="true" aria-label="' + escAttr(ariaLabel) + '">'
      + '<button type="button" class="receipt-close">×</button>'
      + '<div class="receipt-title"></div>'
      + '<div class="receipt-value">' + escHtml(displayValue) + "</div>"
      + '<ol class="receipt-steps"></ol>'
      + '<div class="receipt-footer"><div class="receipt-raw-label"></div><div class="receipt-raw-links"></div></div>'
      + "</div>";
    document.body.appendChild(overlayEl);
    overlayEl.querySelector(".receipt-backdrop").addEventListener("click", close);
    var closeBtn = overlayEl.querySelector(".receipt-close");
    closeBtn.addEventListener("click", close);
    document.addEventListener("keydown", onKeydown, true);
    return closeBtn;
  }

  function open(ccy, displayValue, triggerEl) {
    if (!ccy) return;
    var closeBtn = openShell(ccy, displayValue, triggerEl);

    getCopy().then(function (copy) {
      if (!overlayEl) return;
      overlayEl.querySelector(".receipt-title").textContent = copy.title || "";
      closeBtn.setAttribute("aria-label", copy.close || "");
      renderLoading(copy);
      closeBtn.focus();
      var file = "data/receipts/" + ccy + ".json";
      fetch(file, { cache: "no-store" })
        .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
        .then(function (receipt) { render(receipt, copy); })
        .catch(function () { renderError(copy, file); });
    });
  }

  // corridor.html's cost-in-bps figures (SEB-178): same shell, a receipt
  // keyed by (corridor, notional, hour) instead of by currency, and its own
  // copy.json templates (receiptCorridor) rather than the index/country
  // ones -- see buildCorridorSteps() for why the two can't share templates
  // (a corridor cost has fee legs, not an official rate).
  function openCorridor(file, regime, displayValue, triggerEl) {
    if (!file) return;
    var closeBtn = openShell(file, displayValue, triggerEl);

    getCorridorCopy().then(function (copy) {
      if (!overlayEl) return;
      overlayEl.querySelector(".receipt-title").textContent = copy.title || "";
      closeBtn.setAttribute("aria-label", copy.close || "");
      renderLoading(copy);
      closeBtn.focus();
      var path = "data/corridor_receipts/" + file + ".json";
      fetch(path, { cache: "no-store" })
        .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
        .then(function (receipt) {
          paintSteps(buildCorridorSteps(receipt, copy, regime), receipt.source_files, copy.rawFilesLabel);
        })
        .catch(function () { renderError(copy, path); });
    });
  }

  // fee-tiers.html's crossover paragraph and tier rows (SEB-192): same
  // shell, fed from data/crossover_receipts/<regime>_<hour>.json and
  // copy.json's "receiptCrossover" templates -- see buildCrossoverSteps().
  function openCrossover(file, displayValue, triggerEl) {
    if (!file) return;
    var closeBtn = openShell(file, displayValue, triggerEl);

    getCrossoverCopy().then(function (copy) {
      if (!overlayEl) return;
      overlayEl.querySelector(".receipt-title").textContent = copy.title || "";
      closeBtn.setAttribute("aria-label", copy.close || "");
      renderLoading(copy);
      closeBtn.focus();
      var path = "data/crossover_receipts/" + file + ".json";
      fetch(path, { cache: "no-store" })
        .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
        .then(function (receipt) {
          paintSteps(buildCrossoverSteps(receipt, copy), receipt.source_files, copy.rawFilesLabel);
        })
        .catch(function () { renderError(copy, path); });
    });
  }

  // sending-money.html's "every price change" list (SEB-187): same shell,
  // fed from data/pricechange_receipts/<key>.json and copy.json's
  // "receiptPriceChange" templates -- see buildPriceChangeSteps().
  function openPriceChange(key, displayValue, triggerEl) {
    if (!key) return;
    var closeBtn = openShell(key, displayValue, triggerEl);

    getPriceChangeCopy().then(function (copy) {
      if (!overlayEl) return;
      overlayEl.querySelector(".receipt-title").textContent = copy.title || "";
      closeBtn.setAttribute("aria-label", copy.close || "");
      renderLoading(copy);
      closeBtn.focus();
      var path = "data/pricechange_receipts/" + key + ".json";
      fetch(path, { cache: "no-store" })
        .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
        .then(function (receipt) {
          paintSteps(buildPriceChangeSteps(receipt, copy), receipt.source_files, copy.rawFilesLabel);
        })
        .catch(function () { renderError(copy, path); });
    });
  }

  // sending-money.html's provider-ranking cost figures (SEB-186): same
  // shell, a receipt file keyed by (corridor, size, hour) holding one row
  // per provider, and its own copy.json templates (receiptProvider) rather
  // than the index/country ones -- see buildProviderSteps() for why.
  function openProvider(file, providerName, displayValue, triggerEl) {
    if (!file || !providerName) return;
    var closeBtn = openShell(providerName, displayValue, triggerEl);

    getProviderCopy().then(function (copy) {
      if (!overlayEl) return;
      overlayEl.querySelector(".receipt-title").textContent = copy.title || "";
      closeBtn.setAttribute("aria-label", copy.close || "");
      renderLoading(copy);
      closeBtn.focus();
      var path = "data/provider_receipts/" + file + ".json";
      fetch(path, { cache: "no-store" })
        .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
        .then(function (receipt) {
          var row = (receipt.rows || []).filter(function (x) { return x.provider === providerName; })[0];
          if (!row) throw new Error("no such provider in this receipt");
          paintSteps(buildProviderSteps(row, copy), row.source_files, copy.rawFilesLabel);
        })
        .catch(function () { renderError(copy, path); });
    });
  }

  // how-it-was-built.html's two JSON-backed meter tiles (SEB-190): same
  // shell, a receipt file keyed by (meter, day), and its own copy.json
  // templates (receiptMeter) rather than the index/country ones -- see
  // buildMeterSteps() for why.
  function openMeter(file, displayValue, triggerEl) {
    if (!file) return;
    var closeBtn = openShell(file, displayValue, triggerEl);

    getMeterCopy().then(function (copy) {
      if (!overlayEl) return;
      overlayEl.querySelector(".receipt-title").textContent = copy.title || "";
      closeBtn.setAttribute("aria-label", copy.close || "");
      renderLoading(copy);
      closeBtn.focus();
      var path = "data/meter_receipts/" + file + ".json";
      fetch(path, { cache: "no-store" })
        .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
        .then(function (receipt) {
          paintSteps(buildMeterSteps(receipt, copy), receipt.source_files, copy.rawFilesLabel);
        })
        .catch(function () { renderError(copy, path); });
    });
  }

  document.addEventListener("click", function (e) {
    var t = e.target.closest && e.target.closest(
      "[data-receipt-ccy],[data-receipt-corridor-file],[data-receipt-crossover-file],[data-receipt-provider-file],[data-pricechange-key],[data-receipt-meter-file]");
    if (!t) return;
    e.preventDefault();
    var displayValue = t.getAttribute("data-receipt-value") || t.textContent;
    if (t.hasAttribute("data-receipt-meter-file")) {
      openMeter(t.getAttribute("data-receipt-meter-file"), displayValue, t);
    } else if (t.hasAttribute("data-receipt-corridor-file")) {
      openCorridor(t.getAttribute("data-receipt-corridor-file"),
        t.getAttribute("data-receipt-regime") || "taker", displayValue, t);
    } else if (t.hasAttribute("data-receipt-crossover-file")) {
      openCrossover(t.getAttribute("data-receipt-crossover-file"), displayValue, t);
    } else if (t.hasAttribute("data-pricechange-key")) {
      openPriceChange(t.getAttribute("data-pricechange-key"), displayValue, t);
    } else if (t.hasAttribute("data-receipt-provider-file")) {
      openProvider(t.getAttribute("data-receipt-provider-file"),
        t.getAttribute("data-receipt-provider-name"), displayValue, t);
    } else {
      open(t.getAttribute("data-receipt-ccy"), displayValue, t);
    }
  });

  window.Receipt = { close: close };
})();
