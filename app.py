import pickle
import json
import numpy as np
from flask import Flask, request, jsonify

app = Flask(__name__)
models = {}
encoders = {}

def load_models():
    for name, path in [('eta','eta_model.pkl'),('fare','fare_model.pkl'),('traffic','traffic_model.pkl'),('departure','depart_model.pkl'),('reliability','reliability_model.pkl'),('safety','safety_model.pkl')]:
        with open(path,'rb') as f: models[name] = pickle.load(f)
    for name, path in [('transport','le_transport.pkl'),('day','le_day.pkl'),('route','le_route.pkl')]:
        with open(path,'rb') as f: encoders[name] = pickle.load(f)
    with open('feature_config.json') as f: return json.load(f)

config = load_models()

def safe_encode(enc, val):
    try: return int(enc.transform([val])[0])
    except: return 0

def traffic_mult(hour, is_wk):
    if is_wk: return 1.2 if 10<=hour<=14 else 1.0
    if 6<=hour<=8: return 1.8
    if 9<=hour<=10: return 1.4
    if 15<=hour<=18: return 1.7
    if 19<=hour<=20: return 1.3
    return 0.9

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "app": "TransIQ ML API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": ["/health", "/predict", "/plan"]
    })

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status':'healthy','models_loaded':list(models.keys())})

@app.route('/predict', methods=['POST'])
def predict():
    try:
        d = request.get_json()
        hour = int(d.get('hour_of_day',8))
        is_wk = int(d.get('is_weekend',0))
        is_peak = 1 if (6<=hour<=9 or 16<=hour<=19) else 0
        traf = traffic_mult(hour, is_wk)
        t_enc = safe_encode(encoders['transport'], d.get('transport_type',''))
        d_enc = safe_encode(encoders['day'], d.get('day_of_week','Mon'))
        r_enc = safe_encode(encoders['route'], d.get('route_id','R001'))
        dist = float(d.get('distance_km',10))
        bf = float(d.get('base_fare_jmd',200))
        bd = float(d.get('base_duration_min',40))
        eta   = max(5,  int(models['eta'].predict([[hour,is_peak,is_wk,t_enc,dist,traf,d_enc,r_enc,bd]])[0]))
        fare  = max(50, int(models['fare'].predict([[hour,is_peak,t_enc,bf,dist,d_enc,traf,is_wk]])[0]))
        traf_pred = round(float(models['traffic'].predict([[hour,is_peak,is_wk,d_enc,r_enc,t_enc]])[0]),2)
        dep   = max(5,  int(models['departure'].predict([[r_enc,t_enc,dist,is_wk,bd]])[0]))
        rel   = round(float(models['reliability'].predict([[r_enc,t_enc,hour,is_peak,is_wk,d_enc,dist,traf]])[0]),1)
        saf   = round(float(models['safety'].predict([[hour,is_peak,is_wk,t_enc,traf,d_enc,r_enc]])[0]),1)
        traf_label = 'Heavy' if traf_pred>=1.7 else ('Moderate' if traf_pred>=1.3 else 'Clear')
        return jsonify({'status':'success','predictions':{
            'eta_minutes':eta, 'fare_jmd':fare,
            'traffic_multiplier':traf_pred, 'traffic_label':traf_label,
            'best_departure_hour':dep, 'reliability_score':min(100,max(0,rel)),
            'safety_score':min(100,max(0,saf))
        }})
    except Exception as e:
        return jsonify({'status':'error','message':str(e)}), 500

@app.route('/plan', methods=['POST'])
def plan():
    try:
        data   = request.get_json()
        start  = data.get('start_hub')
        end    = data.get('end_hub')
        budget = float(data.get('budget_jmd', 500))
        hour   = int(data.get('hour_of_day', 7))
        day    = data.get('day_of_week', 'Mon')
        is_wk  = int(data.get('is_weekend', 0))

        all_routes = [
            {"route_id":"R001","transport_type":"Route Taxi","distance_km":18.2,"base_fare_jmd":250,"base_duration_min":45,"start_hub":"Spanish Town","end_hub":"Half Way Tree"},
            {"route_id":"R002","transport_type":"JUTC Bus","distance_km":18.2,"base_fare_jmd":150,"base_duration_min":75,"start_hub":"Spanish Town","end_hub":"Half Way Tree"},
            {"route_id":"R014","transport_type":"Uber","distance_km":18.2,"base_fare_jmd":2200,"base_duration_min":35,"start_hub":"Spanish Town","end_hub":"Half Way Tree"},
            {"route_id":"R003","transport_type":"Route Taxi","distance_km":7.5,"base_fare_jmd":200,"base_duration_min":25,"start_hub":"Half Way Tree","end_hub":"Downtown Kingston"},
            {"route_id":"R004","transport_type":"JUTC Bus","distance_km":7.5,"base_fare_jmd":100,"base_duration_min":40,"start_hub":"Half Way Tree","end_hub":"Downtown Kingston"},
            {"route_id":"R005","transport_type":"Route Taxi","distance_km":22.1,"base_fare_jmd":300,"base_duration_min":50,"start_hub":"Portmore","end_hub":"Half Way Tree"},
            {"route_id":"R006","transport_type":"JUTC Bus","distance_km":22.1,"base_fare_jmd":180,"base_duration_min":85,"start_hub":"Portmore","end_hub":"Half Way Tree"},
            {"route_id":"R007","transport_type":"Route Taxi","distance_km":28.4,"base_fare_jmd":400,"base_duration_min":55,"start_hub":"Portmore","end_hub":"Downtown Kingston"},
            {"route_id":"R008","transport_type":"JUTC Bus","distance_km":28.4,"base_fare_jmd":250,"base_duration_min":100,"start_hub":"Portmore","end_hub":"Downtown Kingston"},
            {"route_id":"R009","transport_type":"Route Taxi","distance_km":5.8,"base_fare_jmd":180,"base_duration_min":20,"start_hub":"Half Way Tree","end_hub":"Papine"},
            {"route_id":"R010","transport_type":"JUTC Bus","distance_km":5.8,"base_fare_jmd":100,"base_duration_min":35,"start_hub":"Half Way Tree","end_hub":"Papine"},
            {"route_id":"R011","transport_type":"Route Taxi","distance_km":23.5,"base_fare_jmd":350,"base_duration_min":55,"start_hub":"Spanish Town","end_hub":"Downtown Kingston"},
            {"route_id":"R012","transport_type":"JUTC Bus","distance_km":23.5,"base_fare_jmd":200,"base_duration_min":90,"start_hub":"Spanish Town","end_hub":"Downtown Kingston"},
            {"route_id":"R013","transport_type":"Uber","distance_km":2.9,"base_fare_jmd":800,"base_duration_min":12,"start_hub":"New Kingston","end_hub":"Half Way Tree"},
        ]

        matched = [r for r in all_routes if r['start_hub'] == start and r['end_hub'] == end]

        if not matched:
            return jsonify({"status":"error","message":f"No routes found from {start} to {end}"}), 404

        results = []
        for route in matched:
            is_peak = 1 if (6 <= hour <= 9 or 16 <= hour <= 19) else 0
            traf    = traffic_mult(hour, is_wk)
            t_enc   = safe_encode(encoders['transport'], route['transport_type'])
            d_enc   = safe_encode(encoders['day'], day)
            r_enc   = safe_encode(encoders['route'], route['route_id'])
            dist    = route['distance_km']
            bf      = route['base_fare_jmd']
            bd      = route['base_duration_min']

            eta   = max(5,  int(models['eta'].predict([[hour,is_peak,is_wk,t_enc,dist,traf,d_enc,r_enc,bd]])[0]))
            fare  = max(50, int(models['fare'].predict([[hour,is_peak,t_enc,bf,dist,d_enc,traf,is_wk]])[0]))
            traf_pred = round(float(models['traffic'].predict([[hour,is_peak,is_wk,d_enc,r_enc,t_enc]])[0]),2)
            dep   = max(5,  int(models['departure'].predict([[r_enc,t_enc,dist,is_wk,bd]])[0]))
            rel   = round(float(models['reliability'].predict([[r_enc,t_enc,hour,is_peak,is_wk,d_enc,dist,traf]])[0]),1)
            saf   = round(float(models['safety'].predict([[hour,is_peak,is_wk,t_enc,traf,d_enc,r_enc]])[0]),1)

            traf_label = 'Heavy' if traf_pred >= 1.7 else ('Moderate' if traf_pred >= 1.3 else 'Clear')

            results.append({
                'route':         route,
                'within_budget': fare <= budget,
                'balance_score': (fare / max(budget, 1)) * 0.4 + (eta / 120) * 0.4,
                'predictions': {
                    'eta_minutes':         eta,
                    'fare_jmd':            fare,
                    'traffic_label':       traf_label,
                    'traffic_multiplier':  traf_pred,
                    'best_departure_hour': dep,
                    'reliability_score':   min(100, max(0, rel)),
                    'safety_score':        min(100, max(0, saf)),
                }
            })

        fastest  = min(results, key=lambda x: x['predictions']['eta_minutes'])
        cheapest = min(results, key=lambda x: x['predictions']['fare_jmd'])
        balanced = min(results, key=lambda x: x['balance_score'])

        return jsonify({
            "status": "success",
            "trip": {
                "start_hub":   start,
                "end_hub":     end,
                "budget_jmd":  budget,
                "hour_of_day": hour,
                "day_of_week": day,
            },
            "plans": {
                "fastest":  fastest,
                "cheapest": cheapest,
                "balanced": balanced,
            },
            "all_options": results
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
