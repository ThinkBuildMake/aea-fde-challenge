"""Audit of the 420 supplied transcripts: whole-call intent, how the human agent resolved it, timing, caller noise.
Usage: python3 -I analysis/audit_calls.py data/meridian_dataset  (writes analysis/call_labels.csv, prints the numbers used in docs/AUDIT.md)"""
import glob, re, csv, sys, collections, statistics, datetime as dt

D = sys.argv[1]
OUT = 'analysis/call_labels.csv'

NOISE = re.compile(r"can you hear me|you cut out|i.m driving|my dog is barking|take your time|i can hear you|go ahead", re.I)
GREET = re.compile(r"(speaking|this is \w+|\w+ here)\b.*(what can i do|how can i help|how may i help|what.s going on)", re.I)

# Intent rules applied in order to the caller's substantive turns (noise, names and acknowledgements removed).
INTENTS = [
 ('safety_gas_co_sparks', r'smell gas|carbon monoxide|sparks|smoke'),
 ('safety_burning_smell', r'burning from'),
 ('booking_plus_membership_question', r'two things'),
 ('warranty_recall_or_repeat', r'labor warranty cover a repeat'),
 ('warranty', r'warranty|register my new unit'),
 ('billing_double_charge', r'charged twice'),
 ('billing_quote_mismatch', r'tech quoted me'),
 ('billing_explain_invoice', r'not sure what it.s for'),
 ('billing_balance', r'current balance'),
 ('billing_pay_invoice', r'pay invoice'),
 ('membership_autopay', r'autopay'),
 ('membership_renewal', r'membership is renewing'),
 ('membership_cancel', r'cancel my comfort club'),
 ('membership_upgrade', r'upgrade from'),
 ('membership_info', r'membership actually include|how much is the maintenance plan|joining the maintenance'),
 ('member_new_system_discount', r"i.m a member"),
 ('new_system_quote', r'replacing it|what would that cost'),
 ('refund_demand', r'full refund'),
 ('complaint_manager', r'talk to a manager|called three times|second opinion|speak to someone in charge'),
 ('late_technician', r'my window was'),
 ('appointment_confirm', r'confirm i still have'),
 ('appointment_move', r'something came up|move it|move my'),
 ('appointment_cancel', r'cancel my appointment'),
 ('commercial', r'strip center|rooftop units'),
 ('employment', r'hiring hvac'),
 ('wrong_number', r'meridian dental'),
 ('booking_repair_or_tuneup', r'book a repair|schedule a service call|get someone out|get a tech out|soonest you can get|annual tune-up'),
]
GROUP = {
 'safety_gas_co_sparks': 'Safety', 'safety_burning_smell': 'Safety',
 'booking_repair_or_tuneup': 'Book a visit', 'booking_plus_membership_question': 'Book a visit',
 'warranty': 'Warranty', 'warranty_recall_or_repeat': 'Warranty',
 'membership_info': 'Membership question', 'membership_renewal': 'Membership question', 'member_new_system_discount': 'Membership question',
 'membership_autopay': 'Membership change', 'membership_cancel': 'Membership change', 'membership_upgrade': 'Membership change',
 'billing_balance': 'Billing lookup', 'billing_pay_invoice': 'Billing lookup', 'billing_explain_invoice': 'Billing lookup',
 'billing_double_charge': 'Billing dispute', 'billing_quote_mismatch': 'Billing dispute',
 'appointment_confirm': 'Existing appointment', 'appointment_move': 'Existing appointment', 'appointment_cancel': 'Existing appointment',
 'late_technician': 'Late technician',
 'refund_demand': 'Complaint or refund', 'complaint_manager': 'Complaint or refund',
 'new_system_quote': 'New system quote',
 'commercial': 'Redirect (not residential)', 'employment': 'Redirect (not residential)', 'wrong_number': 'Redirect (not residential)',
}

def parse(path):
    head, body = open(path).read().split('\n\n', 1)
    h = dict(l.split(': ', 1) for l in head.splitlines())
    turns = [tuple(l.split(': ', 1)) for l in body.strip().splitlines()]
    return h, turns

def resolution(agent_text):
    t = agent_text.lower()
    if 'leave the house' in t: return 'safety_stop_instruction'
    if re.search(r'supervisor|service manager', t): return 'supervisor_callback'
    if re.search(r'commercial division|careers page', t): return 'redirect'
    if re.search(r"you're booked|done\. i have|moved\.|warranty diagnostic at no charge|warranty recall|i have an advisor available", t): return 'wrote_to_schedule'
    if re.search(r'auto-renew is off|you.re upgraded|secure link|secure payment link|sending that to the email|sent\. you should', t): return 'action_or_link'
    return 'information_only'

rows = []
for f in sorted(glob.glob(f'{D}/call_transcripts/*.txt')):
    h, turns = parse(f)
    cust = [t for r, t in turns if r == 'Customer']
    agent = [t for r, t in turns if r == 'Agent']
    noise = [t for t in cust if NOISE.search(t)]
    subst = [t for t in cust if not NOISE.search(t)]
    intent = 'UNCLASSIFIED'
    for name, pat in INTENTS:
        if any(re.search(pat, t, re.I) for t in subst): intent = name; break
    first_real = next((t for t in subst if len(t) > 25), '')
    atext = ' '.join(agent)
    rows.append(dict(
        call_id=h['Call ID'], ts=h['Date'], agent=h['Agent'], dur=int(re.sub(r'(\d+)m (\d+)s', lambda m: str(int(m[1]) * 60 + int(m[2])), h['Duration'])),
        turns=len(turns), noise_turns=len(noise), intent=intent, group=GROUP.get(intent, 'Unclassified'),
        resolution=resolution(atext),
        waitlist='waitlist' in atext.lower(), asked_earlier=any('anything earlier' in t for t in cust),
        id_method=('account_number' if any(re.search(r'MHC-\d{5}', t) for t in cust) else
                   'name_address' if any(re.search(r'\d{3,4} [A-Z]', t) for t in cust) else
                   'name_phone' if any(re.search(r'512-\d{3}-\d{4}', t) for t in cust) else
                   'name_only' if any(re.fullmatch(r"(Um, )?[A-Za-z]+ [A-Za-z]+\.?", t) for t in cust) else 'none')))

with open(OUT, 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

N = len(rows)
print(N, 'calls')
print('\n== whole-call intent (detail)')
c = collections.Counter(r['intent'] for r in rows)
for k, v in c.most_common(): print(f'{v:4d} {v/N:5.1%} {k}')
print('\n== driver group')
g = collections.Counter(r['group'] for r in rows)
for k, v in g.most_common():
    ds = [r['dur'] for r in rows if r['group'] == k]
    res = collections.Counter(r['resolution'] for r in rows if r['group'] == k)
    print(f'{v:4d} {v/N:5.1%} median {statistics.median(ds):4.0f}s  {k:28s} {dict(res)}')
print('\n== resolution overall');
for k, v in collections.Counter(r['resolution'] for r in rows).most_common(): print(f'{v:4d} {v/N:5.1%} {k}')
d = [r['dur'] for r in rows]
print('\nduration min/median/p90/max', min(d), statistics.median(d), sorted(d)[int(.9*N)], max(d))
print('noise: calls with >=1 noise turn', sum(1 for r in rows if r['noise_turns']), 'of', N)
sf = collections.Counter()
for r in rows:
    if r['intent'] == 'safety_gas_co_sparks':
        c_ = ' '.join(t for who, t in parse(f"{D}/call_transcripts/{r['call_id']}.txt")[1] if who == 'Customer').lower()
        sf['gas' if 'smell gas' in c_ else 'carbon monoxide' if 'carbon monoxide' in c_ else 'sparks or smoke'] += 1
print('safety stops by cause', dict(sf))
print('id method', collections.Counter(r['id_method'] for r in rows))
print('waitlist calls', sum(r['waitlist'] for r in rows), 'asked earlier', sum(r['asked_earlier'] for r in rows))
print('by human agent', collections.Counter(r['agent'] for r in rows))

# timing
T = [dt.datetime.fromisoformat(r['ts']) for r in rows]
print('\nfirst/last', min(T), max(T), 'days', (max(T)-min(T)).days + 1)
print('by weekday', sorted(collections.Counter(t.strftime('%a') for t in T).items()))
print('by hour', sorted(collections.Counter(t.hour for t in T).items()))
def outside(t):
    wd, hr = t.weekday(), t.hour + t.minute / 60
    if wd == 6: return True
    if wd == 5: return not (8 <= hr < 16)
    return not (7 <= hr < 19)
print('outside published hours', sum(outside(t) for t in T), ' sunday', sum(t.weekday()==6 for t in T))
perday = collections.Counter(t.date() for t in T)
print('calls/day mean', round(statistics.mean(perday.values()),1), 'max', max(perday.values()), 'days with calls', len(perday))
ev = []
for t, r in zip(T, rows): ev += [(t, 1), (t + dt.timedelta(seconds=r['dur']), -1)]
cur = mx = 0
for _, x in sorted(ev): cur += x; mx = max(mx, cur)
print('max simultaneous calls', mx)
print('volume by month', sorted(collections.Counter(t.strftime('%Y-%m') for t in T).items()))
