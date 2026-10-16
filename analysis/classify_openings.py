"""Rule-based intent label from a call's first substantive customer turn(s). Provisional discovery pass."""
import glob, re, collections, csv, statistics, sys
D = sys.argv[1]
RULES = [  # order matters: safety first
 ('safety_emergency', r'smell gas|carbon monoxide|sparks'),
 ('safety_burning_smell', r'burning from'),
 ('book_repair', r'book a repair|schedule a service call|get someone out|get a tech out|soonest you can get a tech|annual tune-up|need my annual'),
 ('reschedule_cancel_appt', r'move it|cancel my appointment'),
 ('confirm_appt', r'confirm i still have'),
 ('late_tech_no_show', r'my window was'),
 ('billing_balance', r"current balance"),
 ('billing_pay_invoice', r'pay invoice'),
 ('billing_explain_invoice', r'not sure what it.s for'),
 ('billing_dispute_quote_mismatch', r'tech quoted me'),
 ('billing_double_charge', r'charged twice'),
 ('membership_autopay', r'autopay'),
 ('membership_renewal_charge', r'membership is renewing'),
 ('membership_what_included', r'membership actually include|how much is the maintenance plan|joining the maintenance'),
 ('membership_cancel', r'cancel my comfort club'),
 ('membership_upgrade', r'upgrade from'),
 ('member_discount_new_system', r"i.m a member"),
 ('warranty_coverage', r'under warranty|labor warranty|warranty transfer|file a warranty|register my new unit'),
 ('new_system_quote', r'replacing it|what would that cost'),
 ('refund_demand', r'full refund'),
 ('complaint_manager', r'talk to a manager|called three times|second opinion|\$4,000 replacement'),
 ('commercial', r'strip center|rooftop units'),
 ('employment', r'hiring hvac'),
 ('wrong_number', r'meridian dental'),
 ('connection_noise', r"you cut out|can you hear me|i.m driving"),
]
def opening(path):
    body = open(path).read().split('\n\n',1)[1].splitlines()
    cust = [l[10:] for l in body if l.startswith('Customer:')]
    return ' '.join(cust[:2]).lower(), ' '.join(cust).lower()
dur = {r['call_id']: int(r['duration_sec']) for r in csv.DictReader(open(f'{D}/call_transcripts_index.csv'))}
lab = {}
for f in sorted(glob.glob(f'{D}/call_transcripts/*.txt')):
    cid = f.split('/')[-1][:-4]
    op, full = opening(f)
    l = 'UNCLASSIFIED'
    for name, pat in RULES:
        if re.search(pat, op): l = name; break
    lab[cid] = l
c = collections.Counter(lab.values())
print(len(lab), 'calls')
for k, v in c.most_common():
    ds = [dur[i] for i in lab if lab[i] == k]
    print(f'{v:4d} {v/len(lab):5.1%} median {statistics.median(ds):5.0f}s  {k}')
csv.writer(open('/home/user/aea-fde-challenge/analysis/provisional_labels.csv','w')).writerows([['call_id','provisional_intent']]+sorted(lab.items()))
