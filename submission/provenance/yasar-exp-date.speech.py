def prepare(service, answer, today, status):
    import re
    import datetime
    from decimal import Decimal, ROUND_HALF_UP
    say = {}
    facts = {}
    out = {"say": say, "facts": facts}
    try:
        ONES = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
        TENS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
        MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
        WEEKS = ["", "birinci", "ikinci", "üçüncü", "dördüncü"]
        CUR = [("debtTL", "Türk Lirası", "kuruş"), ("debtUSD", "Dolar", "sent"), ("debtEUR", "Euro", "sent"), ("debtGBP", "İngiliz Sterlini", "peni")]
        SERVICE_ERR = "Şu anda işleminizi gerçekleştiremiyorum, sizi müşteri temsilcimize aktarıyorum."
        WEEK_ERR = "Şu anda hesap kesim tarihinizi değiştiremiyorum, sizi müşteri temsilcimize aktarıyorum."
        MENU = "Sizi ana menüye yönlendiriyorum."
        OTHER = "Başka bir kartınızın borcunu öğrenmek ister misiniz?"
        WEEK_OFFER = "Hesap kesim tarihinizi değiştirebilirim."

        def words(n):
            if n == 0:
                return "sıfır"
            scales = ["", "bin", "milyon", "milyar", "trilyon", "katrilyon"]
            parts = []
            i = 0
            while n > 0 and i < len(scales):
                n, g = divmod(n, 1000)
                if g:
                    w = []
                    h, r = divmod(g, 100)
                    if h:
                        if h > 1:
                            w.append(ONES[h])
                        w.append("yüz")
                    if r >= 10:
                        w.append(TENS[r // 10])
                    if r % 10:
                        w.append(ONES[r % 10])
                    if i == 1 and g == 1:
                        w = []
                    if scales[i]:
                        w.append(scales[i])
                    parts.insert(0, " ".join(w))
                i += 1
            return None if n > 0 else " ".join(parts)

        def dec(v):
            if v is None or isinstance(v, bool):
                return None
            if isinstance(v, (int, float, Decimal)) or (isinstance(v, str) and re.match(r"^\s*-?\d+(\.\d+)?\s*$", v)):
                try:
                    d = Decimal(str(v).strip())
                    if not d.is_finite():
                        return None
                    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                except Exception:
                    return None
            return None

        def amount(d, key):
            if d is None or d < 0:
                return None
            whole = int(d)
            frac = int((d - whole) * 100)
            w = words(whole)
            if w is None:
                return None
            cname = [c[1] for c in CUR if c[0] == key][0]
            sub = [c[2] for c in CUR if c[0] == key][0]
            if frac == 0:
                return w + " " + cname
            if whole == 0:
                return words(frac) + " " + sub
            return w + " " + ("lira" if key == "debtTL" else cname) + " " + words(frac) + " " + sub

        def lower_tr(s):
            return s.replace("İ", "i").replace("I", "ı").lower()

        def suffix(text):
            t = lower_tr(text)
            v = [c for c in t if c in "aıeioöuü"]
            last = v[-1] if v else "i"
            h = "ı" if last in "aı" else ("i" if last in "ei" else ("u" if last in "ou" else "ü"))
            al = [c for c in t if c.isalpha()]
            hard = bool(al) and al[-1] in "fstkçşhp"
            return "'" + ("t" if hard else "d") + h + "r"

        def pdate(v):
            if not isinstance(v, str):
                return None
            m = re.match(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$", v)
            if not m:
                return None
            try:
                return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except Exception:
                return None

        def sdate(d):
            return str(d.day) + " " + MONTHS[d.month - 1] + " " + str(d.year)

        def digits(s):
            return " ".join((["sıfır"] + ONES[1:])[int(c)] for c in s)

        def last4(d):
            v = d.get("cardNumberLast4")
            s = "" if v is None or isinstance(v, bool) else str(v).strip()
            if re.match(r"^\d{4}$", s):
                return s
            tail = str(d.get("cardNumber") or "").strip()[-4:]
            return tail if re.match(r"^\d{4}$", tail) else None

        def cardname(v):
            if not isinstance(v, str):
                return None
            n = " ".join(v.split())
            if not n or len(n) > 40 or len(n.split()) > 5:
                return None
            if re.search(r"[.!?:;,\"«»<>{}\[\]=/\\|@#]", n):
                return None
            bad = set(["ignore", "instruction", "instructions", "talimat", "talimatları", "kural", "kuralları", "rules",
                       "unut", "yoksay", "söyle", "söyleyin", "oku", "okuyun", "deyin", "system", "prompt", "assistant",
                       "asistan", "müşteriye", "lütfen", "please", "say", "tell", "önceki", "previous", "aktar", "aktarın",
                       "you", "must", "borç", "borcu", "borcunuz", "borçlar", "silindi", "kartınız", "yok", "var", "tüm", "bütün"])
            if set(re.findall(r"[a-zçğıöşü]+", lower_tr(n))) & bad:
                return None
            return n

        def kphrase(l4, name, tail):
            return "Sonu " + digits(l4) + " ile biten " + ((name + " ") if name else "") + tail

        def tr_join(items, word):
            if len(items) <= 1:
                return "".join(items)
            return ", ".join(items[:-1]) + " " + word + " " + items[-1]

        ans = answer if isinstance(answer, dict) else {}
        res = ans.get("result") if isinstance(ans.get("result"), dict) else {}
        data = ans.get("data") if isinstance(ans.get("data"), dict) else {}
        try:
            st = 0 if isinstance(status, bool) else int(status)
        except Exception:
            st = 0
        rc = "" if res.get("returnCode") is None else str(res.get("returnCode")).strip()
        code = str(res.get("code") or res.get("returnCode") or "").strip()
        ok = rc == "1" and st in (200, 0)
        if st == 0:
            facts["http_status"] = "unknown; success was judged by result.returnCode only"

        def fail(week):
            sent = WEEK_ERR if week else SERVICE_ERR
            end = "agent_statement_week_error" if week else "agent_service_error"
            facts["success"] = False
            if st == 401:
                facts["case"] = "HTTP 401: repeat the same call once; if the repeat also fails it is a service failure (G11)"
                say["if_the_repeated_call_fails_again"] = sent
                facts["ending_if_repeat_fails"] = end
            else:
                facts["case"] = "service failure (G11)"
                say["service_failure"] = sent
                facts["ending"] = end
                facts["next"] = "say the failure sentence and end with a transfer to an agent; never the main menu; never claim anything was done; never read the error text or code"

        td = None
        if isinstance(today, str) and re.match(r"^\d{4}-\d{2}-\d{2}", today.strip()):
            try:
                t10 = today.strip()[:10]
                td = datetime.date(int(t10[0:4]), int(t10[5:7]), int(t10[8:10]))
            except Exception:
                td = None

        if service == "cards.list":
            NOCARD = "Ekstre borcunu sorgulayabileceğiniz uygun bir kredi kartınız bulunmuyor. Sizi ana menüye aktarıyorum."
            if not ok:
                if st == 404 and code == "FB_IVR_CHANNEL_102":
                    facts["success"] = False
                    facts["case"] = "1.2: no valid card (404 FB_IVR_CHANNEL_102); this is not a service failure"
                    say["no_eligible_card_ending"] = NOCARD
                    facts["ending"] = "no_eligible_card"
                else:
                    fail(False)
                return out
            facts["success"] = True
            cards = data.get("cards") if isinstance(data.get("cards"), list) else []
            elig = []
            other = []
            for c in cards:
                if not isinstance(c, dict):
                    continue
                item = {}
                item["cardNumber"] = c.get("cardNumber")
                item["last4"] = last4(c)
                item["name"] = cardname(c.get("productName"))
                item["name_usable"] = item["name"] is not None
                (elig if c.get("isMainCard") is True else other).append(item)
            facts["eligible_card_count"] = len(elig)
            facts["eligible_cards"] = elig
            facts["cards_not_eligible_isMainCard_false"] = other
            facts["cardNumber_rule"] = "always send cardNumber exactly as listed here (with asterisks); never build it from digits the caller says"
            if not elig:
                facts["case"] = "1.3: no card with isMainCard true"
                say["no_eligible_card_ending"] = NOCARD
                facts["ending"] = "no_eligible_card"
                return out
            if len(elig) == 1:
                facts["case"] = "1.5: exactly one eligible card; it is the card"
                facts["cardNumber_to_send_to_cards.balance"] = elig[0]["cardNumber"]
                facts["next"] = "ask nothing; call cards.balance with this cardNumber (and contact.email.get in the same turn) before speaking; never ask the other-card question in this call"
                if not elig[0]["name_usable"]:
                    facts["card_name"] = "no usable name: refer to the card only by its last four digits"
                return out
            names = []
            for c in elig:
                if c["name"] and c["name"] not in names:
                    names.append(c["name"])
            facts["distinct_card_names"] = names
            base = "Hangi kartınızın borcunu öğrenmek istersiniz?"
            if len(names) >= 2:
                q = base + " Örneğin, " + names[0] + " veya " + names[1] + " diyebilirsiniz."
                facts["case"] = "1.6: several eligible cards with at least two different names; ask the selection question"
                say["card_selection_question"] = q
            elif len(names) == 1 and all(c["name"] == names[0] for c in elig):
                q = names[0] + " isimli birden fazla kartınız var. Kartınızın son dört hanesini söyler misiniz?"
                facts["case"] = "1.6/1.8a: all eligible cards share one name; skip the selection question and ask for the last four digits"
                say["ask_last_four_all_cards_share_one_name"] = q
            else:
                q = base + ((" Örneğin, " + names[0] + " diyebilirsiniz.") if names else "")
                facts["case"] = "several eligible cards but fewer than two usable names; a card without a name is never used as an example and is referred to only by its last four digits"
                say["card_selection_question"] = q
            say["if_name_fits_no_card_or_card_not_on_list"] = "Bu isimde bir kartınız bulunmuyor. " + q
            say["if_caller_wants_all_cards"] = "Borçlarınızı kart kart okuyabiliyorum. " + q
            if other:
                say["if_caller_picks_a_card_with_isMainCard_false"] = "Bu kartınız için ekstre borcu sorgulanamıyor. Başka bir kartınızı söyler misiniz?"
            gi = 0
            dup = False
            for nm in names:
                grp = [c for c in elig if c["name"] == nm]
                if len(grp) < 2:
                    continue
                gi += 1
                tag = "same_name_group_" + str(gi)
                facts[tag] = nm + ": " + str(len(grp)) + " eligible cards, last four " + ", ".join(str(c["last4"]) for c in grp)
                say["ask_last_four_if_caller_picks_" + tag] = nm + " isimli birden fazla kartınız var. Kartınızın son dört hanesini söyler misiniz?"
                seen = []
                for c in grp:
                    l = c["last4"]
                    same = [x for x in grp if x["last4"] == l]
                    if l and l not in seen and len(same) > 1:
                        seen.append(l)
                        dup = True
                        say["ask_last_six_if_last_four_" + l + "_given_in_" + tag] = "Son dört hanesi " + digits(l) + " olan birden fazla kartınız var. Kartınızın son altı hanesini söyler misiniz?"
                        hid = any(not str(x["cardNumber"] or "")[-6:-4].isdigit() for x in same)
                        facts["after_six_digits_for_last_four_" + l + "_in_" + tag] = ("fifth and sixth digits from the end are hidden: go on to the full-number question (1.8c)" if hid
                                                                                       else "compare the six digits with cardNumber; if more than one card still matches go to the full-number question (1.8c)")
            if dup:
                say["ask_full_card_number_if_last_six_do_not_decide"] = "Son altı hanesi aynı olan birden fazla kartınız var. Kart numaranızı söyler misiniz?"
            facts["next"] = ("a name fitting exactly one card -> cards.balance with that card's cardNumber, no confirmation sentence; a partial name fitting several names -> read back just those names and ask which; "
                             "never say back digits the caller said; three tries per question, then the tries-exhausted ending (G12)")
            return out

        if service == "cards.balance":
            if not ok:
                fail(False)
                return out
            facts["success"] = True
            l4 = last4(data)
            name = cardname(data.get("productName"))
            facts["card_last_four"] = l4 if l4 else "missing: no reading sentence can be built from this answer"
            facts["card_name"] = name if name else "no usable name: refer to the card only as 'Sonu ... ile biten kartınız'"
            facts["cardNumber_rule"] = "do not use the cardNumber of this answer; keep the one from cards.list"

            def gd(k):
                v = data.get(k)
                if v is None or (isinstance(v, str) and not v.strip()):
                    return "empty", None
                d = pdate(v)
                return ("ok", d) if d else ("unusable", None)
            sd_state, sd = gd("statementDate")
            lp_state, lpd = gd("lastPayDate")
            ns_state, nsd = gd("nextStatementDate")
            for k, s_ in (("statementDate", sd_state), ("lastPayDate", lp_state), ("nextStatementDate", ns_state)):
                if s_ != "ok":
                    facts[k] = s_ + ": never say this date"
            blocks = []
            missing = []
            debt = []
            nod = []
            unusable = []
            for key, cname, sub in CUR:
                b = data.get(key)
                if isinstance(b, dict) and b:
                    blocks.append((key, cname, b))
                    y = dec(b.get("remainingDebt"))
                    if y is None:
                        unusable.append(cname)
                    elif y > 0:
                        debt.append(cname)
                    else:
                        nod.append(cname)
                else:
                    missing.append(cname)
            facts["currency_blocks_missing_neither_read_nor_named"] = missing
            facts["currencies_with_remaining_debt"] = debt
            facts["currencies_with_remaining_debt_zero_or_negative"] = nod
            if unusable:
                facts["currencies_with_unusable_remainingDebt_left_out"] = unusable
            if l4 is None:
                return out

            def kp(tail):
                return kphrase(l4, name, tail)

            def total_lines():
                lines = []
                for key, cname, b in blocks:
                    t = dec(b.get("totalDebt"))
                    a = amount(t, key) if (t is not None and t > 0) else None
                    if a is None:
                        continue
                    if not lines:
                        lines.append(kp("kartınızın") + " toplam " + cname + " borcu " + a + ".")
                    else:
                        lines.append("Toplam " + cname + " borcunuz " + a + ".")
                if not lines:
                    lines.append(kp("kartınızın") + " toplam borcu bulunmamaktadır.")
                return lines

            no_debt_branch = False
            parts = []
            if sd_state == "empty":
                facts["case"] = "A: statementDate is empty (no statement cut yet)"
                parts.append(kp("kartınızın") + " henüz kesilmiş bir ekstresi olmadığı için ekstre borcunuz bulunmamaktadır.")
                if nsd:
                    parts.append("İlk hesap kesim tarihiniz " + sdate(nsd) + " olacak.")
                say["if_caller_asks_for_statement_by_email"] = "Kartınızın henüz kesilmiş bir ekstresi olmadığı için ekstre gönderemiyorum."
                facts["statement_by_email"] = "not possible for this card (4.3): do not call statement.pdf.send"
                no_debt_branch = True
            elif sd_state == "unusable":
                facts["case"] = "statementDate is present but unusable: the reading cannot be built; nothing is invented"
                return out
            elif td is None:
                facts["case"] = "today is unknown: readings B, C, D and E depend on today's date, so no reading sentence and no date decision is given"
                return out
            else:
                facts["statementDate_to_send_to_statement.pdf.send"] = data.get("statementDate")
                if lpd:
                    facts["lastPayDate_vs_today"] = "today" if lpd == td else ("already passed" if td > lpd else "still ahead")
                    facts["due_date_spoken"] = "bugün" if lpd == td else sdate(lpd)
                top = str(data.get("statementPaymentStatus") or "").strip()
                if td == sd or (nsd is not None and td == nsd):
                    facts["case"] = "B: the statement is cut today; read the total debt, not the statement debt"
                    parts.append("Hesap kesim tarihiniz bugün, ekstreniz saat 00.00 itibarıyla kesilecek.")
                    parts.extend(total_lines())
                elif top == "NO_DEBT" or not debt:
                    facts["case"] = "C: no debt from the statement"
                    no_debt_branch = True
                    parts.append(kp("kartınızın") + " " + sdate(sd) + " tarihli ekstresinden borcunuz bulunmamaktadır.")
                    tl = data.get("debtTL") if isinstance(data.get("debtTL"), dict) else {}
                    t = dec(tl.get("totalDebt"))
                    a = amount(t, "debtTL") if (t is not None and t > 0) else None
                    if t is None or (t > 0 and a is None):
                        facts["debtTL.totalDebt"] = "missing or unusable: the total-debt sentence is left out"
                    elif t > 0:
                        parts.append("Gelecek dönemler dahil toplam borcunuz " + a + suffix(a) + ".")
                    else:
                        facts["debtTL.totalDebt"] = "zero or negative: never read it"
                        parts.append("Gelecek dönemler dahil toplam Türk Lirası borcunuz bulunmamaktadır.")
                    if lpd:
                        parts.append("Son ödeme tarihiniz " + sdate(lpd) + " olacaktır.")
                elif lpd is not None and td > lpd:
                    facts["case"] = "D: today is after lastPayDate; read the total debt"
                    parts.append(kp("kartınızın") + " son ödeme tarihi geçmiştir.")
                    parts.extend(total_lines())
                    tl = data.get("debtTL") if isinstance(data.get("debtTL"), dict) else {}
                    ra = dec(tl.get("remainAutomaticPaymentAmount"))
                    auto = str(data.get("automaticPaymentFlag") or "").strip() == "Y" and ra is not None and ra > 0
                    facts["automatic_payment_remainder_sentence"] = "applies" if auto else "does not apply"
                    a = amount(ra, "debtTL") if auto else None
                    if a:
                        parts.append("Otomatik ödeme talimatınızdan kalan tutar " + a + suffix(a) + ".")
                else:
                    facts["case"] = "E: normal statement reading"
                    lines = []
                    for key, cname, b in blocks:
                        tr = dec(b.get("transferAmount"))
                        if key != "debtTL" and tr is not None and tr > 0:
                            lines.append(cname + " borcunuzun bir kısmı Türk Lirası borcunuza aktarılmıştır.")
                    nread = 0
                    skipped = []
                    for key, cname, b in blocks:
                        if cname not in debt:
                            continue
                        x = dec(b.get("statementDebt"))
                        z = dec(b.get("minPayment"))
                        t = dec(b.get("remainingMinPayment"))
                        ax = amount(x, key)
                        ay = amount(dec(b.get("remainingDebt")), key)
                        az = amount(z, key)
                        at = amount(t, key)
                        s = None
                        if key != "debtTL":
                            if ax and ay and az:
                                s = cname + " borcunuz " + ax + ", kalan toplam borcunuz " + ay + ", ödenmesi gereken minimum tutar " + az + suffix(az) + "."
                        elif t is not None and t <= 0:
                            facts["turkish_lira_payment_state"] = "minimum or more paid"
                            if ax and ay:
                                s = "Türk Lirası borcunuz " + ax + ", kalan toplam borcunuz " + ay + suffix(ay) + ". Minimum ödemenizi yaptığınız için teşekkür ederiz."
                        elif t is not None and z is not None and t >= z:
                            facts["turkish_lira_payment_state"] = "nothing paid"
                            if ax and az:
                                s = "Türk Lirası borcunuz " + ax + ", ödenmesi gereken minimum tutar " + az + suffix(az) + "."
                        elif t is not None and z is not None:
                            facts["turkish_lira_payment_state"] = "less than the minimum paid"
                            if ax and ay and az and at:
                                s = "Türk Lirası borcunuz " + ax + ", ödenmesi gereken minimum tutar " + az + ", kalan toplam borcunuz " + ay + ", kalan minimum ödeme tutarınız " + at + suffix(at) + "."
                        if s:
                            lines.append(s)
                            nread += 1
                        else:
                            skipped.append(cname)
                    if skipped:
                        facts["currency_sentences_left_out_missing_or_unusable_amounts"] = skipped
                    if nread == 0:
                        facts["reading"] = "left out: no currency sentence could be completed from this answer"
                        return out
                    lines[0] = kp("kartınıza") + " ait " + sdate(sd) + " tarihinde kesilen ekstre " + lines[0]
                    parts.extend(lines)
                    if nod:
                        parts.append(tr_join(nod, "ve") + " borcunuz bulunmamaktadır.")
                    if lpd is not None and lpd == td:
                        parts.append("Borçlarınız için son ödeme tarihiniz bugündür.")
                    elif lpd is not None:
                        parts.append("Borçlarınız için son ödeme tarihiniz " + sdate(lpd) + suffix(words(lpd.year)) + ".")
                    else:
                        facts["due_date_sentence"] = "left out: lastPayDate is missing or unusable"
            say["debt_reading"] = " ".join(parts)
            if no_debt_branch:
                say["after_reading_if_another_eligible_card_is_not_yet_read"] = OTHER
                say["after_reading_if_no_other_card_or_caller_says_no"] = MENU
                facts["next"] = ("2.7: no offer in this branch. Another eligible card not yet read -> ask the other-card question (yes -> card selection, or read the only remaining card directly; no -> main-menu sentence, ending main_menu_done). "
                                 "No other card -> main-menu sentence right after the reading, ending main_menu_done. Serve e-mail or statement week only if the caller asks for it.")
            else:
                say["after_reading_if_several_eligible_cards_and_one_not_yet_read"] = OTHER
                say["if_caller_wants_nothing_else"] = MENU
                facts["next"] = ("Step 3: with more than one eligible card and one not yet read, end the reading with the other-card question and do not make the offer yet; with a single eligible card never ask it. "
                                 "Otherwise the offer follows in the same turn, and contact.email.get must be answered before the offer is said.")
            return out

        if service == "contact.email.get":
            if not ok:
                fail(False)
                if st != 401:
                    facts["next"] = "first say the debt reading already obtained, then the failure sentence, and end with a transfer to an agent (agent_service_error)"
                return out
            facts["success"] = True
            raw = data.get("ibanEmail")
            email = raw.strip() if isinstance(raw, str) else ""
            ctype = str(data.get("communicationType") or "").strip()
            registered = bool(email) and ctype.lower() != "phone"
            facts["registered_email_exists"] = registered
            facts["offer_rule"] = "the offer is said once, after the due date or after the 'no' to the other-card question; it applies to the card just read"
            NOMAIL = "Bankamızda kayıtlı bir e-posta adresiniz bulunmadığı için ekstrenizi gönderemiyorum."
            if not registered:
                facts["case"] = "no registered e-mail: never mention or offer e-mail; never take an address from the caller"
                say["offer_if_week_change_still_possible"] = WEEK_OFFER
                say["if_caller_asks_for_email_and_week_change_still_possible"] = NOMAIL + " " + WEEK_OFFER
                say["if_caller_asks_for_email_and_week_change_not_possible"] = NOMAIL + " " + MENU
                facts["offer_if_week_already_changed"] = "no offer at all"
                return out
            facts["case"] = "registered e-mail exists"
            facts["emailAddress_to_send_to_statement.pdf.send"] = email
            say["offer_if_week_change_still_possible"] = "Hesap kesim tarihinizi değiştirebilirim ya da ekstrenizi kayıtlı mail adresinize gönderebilirim."
            say["offer_if_week_already_changed_this_call_or_this_year"] = "Ekstrenizi kayıtlı mail adresinize gönderebilirim."
            tts = data.get("ttsEmail")
            tts = tts.strip() if isinstance(tts, str) and tts.strip() else email
            m = re.match(r"^([^@\s]+)@([^@\s]+)$", tts)
            ask = None
            if m:
                local = m.group(1)
                dom = m.group(2)
                messy = (not re.match(r"^[A-Za-z.]+@[A-Za-z.]+$", tts)) or local.count(".") > 1 or dom.count(".") > 2 or len(local) > 20 or len(dom) > 25
                letters = [c for c in local if c.isalpha()]
                if not messy:
                    ask = "Ekstrenizi " + tts + " adresine göndermemi ister misiniz?"
                    facts["address_reading"] = "short readable address: said as it is, never spelled letter by letter"
                elif letters and dom.split(".")[0]:
                    ask = "Ekstrenizi " + lower_tr(letters[0]) + " ile başlayan " + dom.split(".")[0] + " adresinize göndermemi ister misiniz?"
                    facts["address_reading"] = "long or messy address: shortened to first letter and provider, never spelled"
            if ask:
                say["email_confirmation_question"] = ask
                say["if_caller_gives_another_address"] = "Ekstrenizi yalnızca bankamızda kayıtlı e-posta adresinize gönderebilirim. " + ask
            else:
                facts["address_reading"] = "the address cannot be read in the script's form: the confirmation question is left out"
            say["if_caller_says_the_address_is_wrong"] = "E-posta adresinizi bu görüşmede değiştiremiyorum. " + MENU
            say["if_caller_wants_an_earlier_statement"] = "Yalnızca son kesilen ekstrenizi gönderebilirim."
            say["if_caller_wants_paper_or_text_message"] = "Ekstrenizi yalnızca kayıtlı e-posta adresinize gönderebilirim. " + MENU
            say["if_caller_says_no_to_sending"] = MENU
            facts["next"] = "call statement.pdf.send only after the confirmation question got a clear yes (hedged answer: ask again, three tries); only the latest statement, only this address; at most three sends per call"
            return out

        if service == "statement.week.get":
            if not ok:
                fail(True)
                return out
            facts["success"] = True
            l4 = last4(data)
            name = cardname(data.get("productName"))
            w = data.get("statementWeek")
            ws = "" if w is None or isinstance(w, bool) else str(w).strip()
            wk = int(ws) if ws in ("1", "2", "3", "4") else None
            facts["current_week"] = wk if wk else "missing or unusable: the current-state and option sentences are left out"
            facts["statementDay_to_send_to_decide_and_change"] = data.get("statementDay")
            rel = data.get("relationType")
            rel = rel.strip() if isinstance(rel, str) else ""
            facts["relationType"] = rel if rel else "empty (own statement)"
            if rel not in ("", "M", "C"):
                facts["relationType_note"] = "unknown value: treated as own statement"
                rel = ""
            nsd = pdate(data.get("nextStatementDate"))
            nlp = pdate(data.get("nextLastPayDate"))
            rname = cardname(data.get("relatedCardProductName"))
            rl = str(data.get("relatedCardNumber") or "").strip()[-4:]
            rl = rl if re.match(r"^\d{4}$", rl) else None
            head = None
            if wk and rel == "" and (name or l4):
                head = (name + " kartınızın") if name else kphrase(l4, None, "kartınızın")
            elif wk and rel in ("M", "C") and l4 and rl:
                link = " ile buna bağlı sonu " if rel == "M" else " ile bu kartın bağlı olduğu sonu "
                head = kphrase(l4, name, "kartınız") + link + digits(rl) + " ile biten " + ((rname + " ") if rname else "") + "kartınızın"
            if head:
                s = head + " hesap kesim tarihi her ayın " + WEEKS[wk] + " haftası olarak tanımlı."
                if nsd and nlp:
                    s += " Bir sonraki hesap kesim tarihiniz " + sdate(nsd) + ", son ödeme tarihiniz " + sdate(nlp) + "."
                else:
                    facts["next_dates"] = "nextStatementDate or nextLastPayDate missing or unusable: the dates sentence is left out"
                say["current_state"] = s
            else:
                facts["current_state_sentence"] = "left out: a needed value (week, last four digits or linked card digits) is missing"
            say["question_if_caller_has_not_clearly_asked_for_the_change"] = "Hesap kesim tarihinizi değiştirmek ister misiniz?"
            say["if_caller_does_not_want_to_change"] = MENU
            if wk:
                others = [i for i in (1, 2, 3, 4) if i != wk]
                facts["weeks_that_may_be_offered"] = others
                facts["week_never_offered_and_never_sent_to_decide"] = wk
                opt = "Hesap kesim tarihinizi yılda bir kez değiştirebilirsiniz. Hesap kesim tarihinizi ayın " + tr_join([WEEKS[i] for i in others], "ya da") + " haftasına alabilirim. Hangisini tercih edersiniz?"
                say["week_options"] = opt
                say["if_caller_picks_the_current_week"] = "Hesap kesim tarihiniz zaten bu haftada, değişiklik gerekmiyor. " + opt
            if rel in ("M", "C"):
                who = ((rname + " ") if rname else (("sonu " + digits(rl) + " ile biten ") if rl else None))
                if who:
                    pre = "Bu değişiklik kartınıza bağlı " if rel == "M" else "Bu değişiklik kartınızın bağlı olduğu "
                    say["joint_statement_warning_before_the_confirmation_question"] = pre + who + "kartınızı da etkileyecek."
                facts["joint_statement"] = "yes: the warning sentence must be said after the preview and before 'Onaylıyor musunuz?'"
            else:
                facts["joint_statement"] = "no: no warning sentence"
            say["if_week_already_changed_this_year_or_in_this_call"] = "Hesap kesim tarihinizi yılda bir kez değiştirebilirsiniz."
            facts["next"] = ("after the current state: ask the change question unless the caller already clearly asked (then read the options) or already named a target week (then go to the preview); "
                             "a day, a date or anything else than an offered week -> read the options again, three tries; statement.week.decide only for an offered week")
            return out

        if service == "statement.week.decide":
            rcode = dec(data.get("responseCode"))
            if not (ok and rcode is not None and rcode == 0):
                fail(True)
                return out
            facts["success"] = True
            facts["case"] = "preview only: nothing was changed yet"
            d1 = pdate(data.get("statementDate"))
            d2 = pdate(data.get("statementDueDate"))
            if d1 and d2:
                dates = "Yeni hesap kesim tarihiniz " + sdate(d1) + ", son ödeme tarihiniz " + sdate(d2)
                for i in (1, 2, 3, 4):
                    say["preview_reading_if_the_chosen_week_is_" + str(i)] = "Yeni hesap kesim haftanız her ayın " + WEEKS[i] + " haftası olacak. " + dates + " olacak."
                say["dates_part_of_the_success_sentence_after_the_change_succeeds"] = dates + "."
                facts["new_closing_date_spoken"] = sdate(d1)
                facts["new_due_date_spoken"] = sdate(d2)
            else:
                facts["preview_dates"] = "statementDate or statementDueDate missing or unusable: the preview sentences are left out; never invent a date"
            say["confirmation_question"] = "Onaylıyor musunuz?"
            say["if_the_answer_is_hedged"] = "Değişikliği onaylıyor musunuz, evet mi hayır mı?"
            say["if_caller_says_no"] = MENU
            facts["next"] = ("always confirm, even if the caller says not to ask: preview reading for the chosen week, then the joint-statement warning if the card has one, then the confirmation question; "
                             "only a clear 'evet' counts (three tries); then call statement.week.change exactly once with the same three fields as this preview")
            return out

        if service == "statement.week.change":
            rcode = dec(data.get("responseCode"))
            if not (ok and rcode is not None and rcode == 0 and data.get("exitState") == "OK"):
                fail(True)
                facts["change"] = "never say it was changed" + ("" if st == 401 else "; do not call statement.week.change again")
                return out
            facts["success"] = True
            facts["case"] = "the statement week was changed; it cannot be changed again in this call"
            w = str(data.get("statementWeek") or "").strip()
            if w in ("1", "2", "3", "4"):
                facts["new_week_spoken"] = WEEKS[int(w)]
            facts["success_sentence"] = ("'Sonu [last four, digit by digit] ile biten [card name] kartınızın hesap kesim haftası her ayın [new week] haftası olarak değiştirildi.' followed by the dates part from the preview "
                                         "(statement.week.decide); ignore statementDay of this answer")
            say["after_the_success_sentence"] = MENU
            say["if_caller_wants_it_undone"] = "Değişiklik gerçekleşti, bu görüşmede geri alınamıyor."
            facts["ending"] = "main_menu_done"
            return out

        if service == "statement.pdf.send":
            if not (ok and data.get("exitState") == "DONE"):
                fail(False)
                facts["sending"] = "never say it was sent" + ("" if st == 401 else "; do not send again")
                return out
            facts["success"] = True
            facts["case"] = "the statement was sent to the registered address"
            say["statement_sent"] = "Ekstreniz kayıtlı e-posta adresinize gönderildi. " + MENU
            facts["ending"] = "main_menu_done"
            facts["if_caller_asks_to_send_again"] = "ask the confirmation question and send again; at most three sends in one call, then the main-menu sentence and end"
            return out

        facts["case"] = "unknown service name: nothing prepared"
        return out
    except Exception:
        facts["note"] = "preparation stopped early; only what is listed here is ready"
        return out
