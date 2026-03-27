import pymongo
from collections import Counter

db = pymongo.MongoClient('mongodb://localhost:27017')['flight_ops']

b = list(db['bookings'].find({}, {
    'agent_type':1, 'origin':1, 'destination':1,
    'price_per_seat_inr':1, 'days_to_flight':1,
    'price_to_floor_ratio':1, 'seats_booked':1
}))
f = list(db['live_flights'].find({}, {
    'origin':1, 'destination':1, 'inventory':1, 'current_pricing':1
}))

total_seats_sold = sum(x.get('seats_booked', 1) for x in b)

print('=== HANDOFF STATE TO AI MANAGERS ===')
print('Total bookings:  ', len(b))
print('Total seats sold:', total_seats_sold)
print()

# By persona
personas = Counter(x.get('agent_type', '?') for x in b)
print('Bookings by persona:')
for k, v in personas.most_common():
    print('  %s: %d' % (k, v))
print()

# By route
routes = Counter('%s->%s' % (x.get('origin','?'), x.get('destination','?')) for x in b)
print('Top routes by bookings:')
for k, v in routes.most_common(6):
    print('  %s: %d' % (k, v))
print()

# DTD distribution
dtd = [x.get('days_to_flight', -1) for x in b if x.get('days_to_flight', -1) >= 0]
if dtd:
    buckets = {'D+1-3':0, 'D+4-7':0, 'D+8-21':0, 'D+22+':0}
    for d in dtd:
        if d <= 3:    buckets['D+1-3'] += 1
        elif d <= 7:  buckets['D+4-7'] += 1
        elif d <= 21: buckets['D+8-21'] += 1
        else:         buckets['D+22+'] += 1
    print('Bookings by days-to-flight:')
    for k, v in buckets.items():
        print('  %s: %d' % (k, v))
    print()

# Price to floor ratio
ratios = [x.get('price_to_floor_ratio') for x in b if x.get('price_to_floor_ratio')]
if ratios:
    avg_ratio = sum(ratios) / len(ratios)
    print('Avg price/floor ratio: %.3f' % avg_ratio)
    print()

# Load factors
lf_data = []
for fl in f:
    inv  = fl.get('inventory', {})
    cap  = inv.get('capacity', 186)
    sold = inv.get('sold', 0)
    if sold > 0:
        lf_data.append((fl.get('origin'), fl.get('destination'), sold, cap, sold/cap*100))

lf_data.sort(key=lambda x: -x[4])
total_cap  = sum(fl.get('inventory',{}).get('capacity',186) for fl in f)
total_sold = sum(fl.get('inventory',{}).get('sold',0) for fl in f)
system_lf  = total_sold / total_cap * 100 if total_cap else 0

print('Flights with bookings: %d of %d' % (len(lf_data), len(f)))
print('System load factor:    %.1f%%' % system_lf)
print()
print('Top 8 by load factor:')
for o, d, s, c, lf in lf_data[:8]:
    bar = '#' * int(lf / 5)
    print('  %s->%s  %d/%d  (%.1f%%)  %s' % (o, d, s, c, lf, bar))
print()
print('READY for AI managers.')