#!/usr/bin/env python3
import argparse
import datetime
import sys
from typing import Dict, List, Tuple

import requests
from dateutil import parser as date_parser
from dateutil.tz import tzlocal, gettz

# Define organ lifespan in hours
ORGAN_LIFESPAN = {
    "kidney": 24,
    "liver": 12,
    "heart": 6,
    "lung": 6,
    "pancreas": 24,
    "intestine": 8,
}

# Expanded mapping for common US airports to their timezones
AIRPORT_TIMEZONES = {
    "HNL": "Pacific/Honolulu",
    "SEA": "America/Los_Angeles",
    "SFO": "America/Los_Angeles",
    "SAN": "America/Los_Angeles",
    "DCA": "America/New_York",
    "JFK": "America/New_York",
    "BOS": "America/New_York",
    "LAX": "America/Los_Angeles",
    "ORD": "America/Chicago",
    "ATL": "America/New_York",
    "DFW": "America/Chicago",
    "DEN": "America/Denver",
    "LGA": "America/New_York",
    "EWR": "America/New_York",
    "IAD": "America/New_York",
    "PHX": "America/Phoenix",
    "MIA": "America/New_York",
    "CLT": "America/New_York"
}


def load_api_key_from_file(filename="user_key") -> str:
    """
    Load API key from a text file.
    The file should contain the key in the format 'client_id:client_secret'.
    """
    try:
        with open(filename, 'r') as file:
            api_key = file.read().strip()
            if ":" not in api_key:
                print(f"Error: API key in {filename} must be in the format 'client_id:client_secret'")
                return ""
            return api_key
    except FileNotFoundError:
        print(f"Error: API key file '{filename}' not found.")
        print(f"Please create a file named '{filename}' with your Amadeus API credentials")
        return ""
    except IOError as e:
        print(f"Error reading API key file: {e}")
        return ""


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Find flights for organ transportation."
    )
    parser.add_argument("--origin", help="City or IATA code of origin")
    parser.add_argument("--destination", help="City or IATA code of destination")
    parser.add_argument("--organ", help="Organ type (e.g., kidney, heart, liver)")
    return parser.parse_args()


def get_user_input(args: argparse.Namespace) -> Tuple[str, str, str, datetime.datetime, str]:
    """
    Get user input from command line arguments or prompt the user.
    """
    origin = args.origin or input("City/IATA code of Origin? ")
    destination = args.destination or input("City/IATA code of Destination? ")
    
    organ = args.organ
    while not organ or organ.lower() not in ORGAN_LIFESPAN:
        if organ:
            print(f"Unknown organ type: {organ}")
        organ = input(f"Organ Type? ({', '.join(ORGAN_LIFESPAN.keys())}) ")
    organ = organ.lower()
    
    current_datetime = datetime.datetime.now(tzlocal())
    print(f"Current Date and Time: {current_datetime.strftime('%Y-%m-%d %I:%M %p %Z')}")
    
    api_key = load_api_key_from_file()
    if not api_key:
        sys.exit(1)
    
    return origin, destination, organ, current_datetime, api_key


def search_amadeus(
    origin: str,
    destination: str,
    current_datetime: datetime.datetime,
    api_key: str
) -> List[Dict]:
    """
    Search for flights using the Amadeus API.
    """
    try:
        auth_url = "https://test.api.amadeus.com/v1/security/oauth2/token"
        if ":" not in api_key:
            print("Error: API key must be in the format 'client_id:client_secret'")
            return []
        client_id, client_secret = api_key.split(":", 1)
        auth_data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret
        }
        auth_response = requests.post(auth_url, data=auth_data)
        auth_response.raise_for_status()
        access_token = auth_response.json().get("access_token")
        if not access_token:
            print("Error: Failed to obtain access token from Amadeus")
            return []
        
        search_url = "https://test.api.amadeus.com/v2/shopping/flight-offers"
        headers = {"Authorization": f"Bearer {access_token}"}
        departure_date = current_datetime.strftime("%Y-%m-%d")
        current_hour = current_datetime.hour
        if current_hour >= 20:  # If it's 8 PM or later, adjust the departure date
            tomorrow = current_datetime #+ datetime.timedelta(hours=4)
            departure_date = tomorrow.strftime("%Y-%m-%d")
        params = {
            "originLocationCode": origin,
            "destinationLocationCode": destination,
            "departureDate": departure_date,
            "adults": 1,
            "max": 100,
            "currencyCode": "USD"
        }
        response = requests.get(search_url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        
        flights = []
        for offer_idx, offer in enumerate(data.get("data", [])):
            price = float(offer.get("price", {}).get("total", 0))
            currency = offer.get("price", {}).get("currency", "USD")
            for itinerary_idx, itinerary in enumerate(offer.get("itineraries", [])):
                # Process every itinerary (direct and connecting flights)
                flight = {
                    "id": f"{offer_idx}_{itinerary_idx}",
                    "price": price,
                    "currency": currency,
                    "segments": [],
                    "total_duration_hours": 0
                }
                first_segment = True
                last_arrival_time = None
                for segment in itinerary.get("segments", []):
                    departure_time_str = segment.get("departure", {}).get("at", "")
                    arrival_time_str = segment.get("arrival", {}).get("at", "")
                    dep_airport = segment.get("departure", {}).get("iataCode", "")
                    arr_airport = segment.get("arrival", {}).get("iataCode", "")
                    
                    departure_time = date_parser.parse(departure_time_str)
                    arrival_time = date_parser.parse(arrival_time_str)
                    
                    if departure_time.tzinfo is None:
                        tz_dep = gettz(AIRPORT_TIMEZONES.get(dep_airport, "UTC"))
                        departure_time = departure_time.replace(tzinfo=tz_dep)
                    if arrival_time.tzinfo is None:
                        tz_arr = gettz(AIRPORT_TIMEZONES.get(arr_airport, "UTC"))
                        arrival_time = arrival_time.replace(tzinfo=tz_arr)
                    
                    duration_hours = (arrival_time - departure_time).total_seconds() / 3600
                    
                    if first_segment:
                        flight["origin"] = dep_airport
                        flight["departure_time"] = departure_time_str
                        flight["departure_time_parsed"] = departure_time.isoformat()
                        first_segment = False
                    layover_hours = 0
                    if last_arrival_time:
                        layover_hours = (departure_time - last_arrival_time).total_seconds() / 3600
                    last_arrival_time = arrival_time
                    
                    segment_data = {
                        "airline": segment.get("carrierCode", ""),
                        "flight_number": f"{segment.get('carrierCode', '')}{segment.get('number', '')}",
                        "departure_airport": dep_airport,
                        "arrival_airport": arr_airport,
                        "departure_time": departure_time_str,
                        "arrival_time": arrival_time_str,
                        "departure_time_parsed": departure_time.isoformat(),
                        "arrival_time_parsed": arrival_time.isoformat(),
                        "duration_hours": round(duration_hours, 1),
                        "layover_hours": round(layover_hours, 1) if layover_hours > 0 else 0
                    }
                    
                    flight["segments"].append(segment_data)
                    flight["total_duration_hours"] += duration_hours
                    if layover_hours > 0:
                        flight["total_duration_hours"] += layover_hours
                
                if flight["segments"]:
                    last_seg = flight["segments"][-1]
                    flight["destination"] = last_seg["arrival_airport"]
                    flight["arrival_time"] = last_seg["arrival_time"]
                    flight["arrival_time_parsed"] = last_seg["arrival_time_parsed"]
                flight["total_duration_hours"] = round(flight["total_duration_hours"], 1)
                if flight.get("origin") == origin and flight.get("destination") == destination:
                    flights.append(flight)
        
        return flights
    except requests.exceptions.RequestException as e:
        print(f"Error querying Amadeus API: {e}")
        return []
    except (ValueError, KeyError) as e:
        print(f"Error processing Amadeus API response: {e}")
        return []



def filter_flights_by_lifespan(
    flights: List[Dict],
    organ: str,
    current_time: datetime.datetime
) -> List[Dict]:
    """
    Filter flights based on the organ's lifespan.
    """
    if organ not in ORGAN_LIFESPAN:
        print(f"Unknown organ type: {organ}")
        return []
    
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=tzlocal())
    
    max_hours = ORGAN_LIFESPAN[organ]
    max_arrival_time = current_time + datetime.timedelta(hours=max_hours)
    
    print(f"Current time: {current_time.isoformat()}")
    print(f"Maximum arrival time: {max_arrival_time.isoformat()}")
    
    valid_flights = []
    for flight in flights:
        try:
            departure_time = date_parser.parse(flight["departure_time_parsed"])
            arrival_time = date_parser.parse(flight["arrival_time_parsed"])
            if departure_time.tzinfo is None:
                tz_dep = gettz(AIRPORT_TIMEZONES.get(flight.get("origin"), "UTC"))
                departure_time = departure_time.replace(tzinfo=tz_dep)
            if arrival_time.tzinfo is None:
                tz_arr = gettz(AIRPORT_TIMEZONES.get(flight.get("destination"), "UTC"))
                arrival_time = arrival_time.replace(tzinfo=tz_arr)
            
            # Convert times to UTC for comparison
            departure_utc = departure_time.astimezone(datetime.timezone.utc)
            arrival_utc = arrival_time.astimezone(datetime.timezone.utc)
            current_utc = current_time.astimezone(datetime.timezone.utc)
            max_arrival_utc = max_arrival_time.astimezone(datetime.timezone.utc)
            
            if departure_utc < current_utc:
                print(f"Skipping flight {flight.get('id', 'unknown')}: departs before current time")
                continue
            if arrival_utc > max_arrival_utc:
                print(f"Skipping flight {flight.get('id', 'unknown')}: arrives after maximum time")
                continue
            
            remaining_hours = (max_arrival_utc - arrival_utc).total_seconds() / 3600
            flight["remaining_lifespan_hours"] = round(remaining_hours, 1)
            valid_flights.append(flight)
        except (ValueError, KeyError) as e:
            print(f"Error processing flight: {e}")
            continue
    return valid_flights


def rank_flights(flights: List[Dict], limit: int = 3) -> List[Dict]:
    """
    Rank flights by remaining lifespan hours (largest first) to maximize 
    the time left for the organ upon arrival.
    """
    if not flights:
        return []
    
    # Sort flights in descending order by remaining_lifespan_hours
    ranked = sorted(
        flights,
        key=lambda x: x.get("remaining_lifespan_hours", 0),
        reverse=True
    )
    
    # Debug information: Print the top sorted flights
    print("\nTop flights sorted by maximizing remaining lifespan:")
    sample_size = min(5, len(ranked))
    for i, flight in enumerate(ranked[:sample_size]):
        segments = len(flight.get('segments', []))
        print(f"  Flight {i+1}: Remaining Lifespan = {flight.get('remaining_lifespan_hours')} hours, "
              f"Total Duration = {flight.get('total_duration_hours')} hours, "
              f"Segments = {segments}, "
              f"Price = ${flight.get('price')}")
    
    return ranked[:limit]


def format_flight_output(flights: List[Dict]) -> str:
    """
    Simplified output: print a concise summary of each flight option with segment details.
    Local times are converted using the airport's timezone.
    """
    if not flights:
        return "No matching flights found."
    
    lines = []
    for i, flight in enumerate(flights, start=1):
        lines.append(f"Option {i}:")
        lines.append(f"  Price: ${flight['price']:.2f} {flight['currency']}")
        lines.append(f"  Total Journey Time: {flight['total_duration_hours']} hours")
        lines.append(f"  Remaining Lifespan on Arrival: {flight['remaining_lifespan_hours']} hours")
        lines.append("  Segments:")
        for j, segment in enumerate(flight["segments"], start=1):
            # Convert departure time to local based on departure airport
            dep_t = date_parser.parse(segment["departure_time"])
            if dep_t.tzinfo is None:
                dep_t = dep_t.replace(tzinfo=gettz(AIRPORT_TIMEZONES.get(segment["departure_airport"], "UTC")))
            dep_local = dep_t.astimezone(gettz(AIRPORT_TIMEZONES.get(segment["departure_airport"], "UTC")))
            # Convert arrival time to local based on arrival airport
            arr_t = date_parser.parse(segment["arrival_time"])
            if arr_t.tzinfo is None:
                arr_t = arr_t.replace(tzinfo=gettz(AIRPORT_TIMEZONES.get(segment["arrival_airport"], "UTC")))
            arr_local = arr_t.astimezone(gettz(AIRPORT_TIMEZONES.get(segment["arrival_airport"], "UTC")))
            
            lines.append(f"    Segment {j}: {segment['airline']} {segment['flight_number']}")
            lines.append(f"      Depart: {segment['departure_airport']} at {dep_local.strftime('%Y-%m-%d %I:%M %p')}")
            lines.append(f"      Arrive: {segment['arrival_airport']} at {arr_local.strftime('%Y-%m-%d %I:%M %p')}")
            lines.append(f"      Duration: {segment['duration_hours']} hours")
            if segment.get('layover_hours', 0) > 0:
                lines.append(f"      Layover: {segment['layover_hours']} hours")
        lines.append("")
    return "\n".join(lines)


def main():
    args = parse_arguments()
    origin, destination, organ, current_datetime, api_key = get_user_input(args)
    
    print(f"\nSearching for flights to transport {organ} from {origin} to {destination}...")
    print(f"Maximum out-of-body time for {organ}: {ORGAN_LIFESPAN.get(organ, 'Unknown')} hours")
    
    flights = search_amadeus(origin, destination, current_datetime, api_key)
    if not flights:
        print("No flights found. Please check your inputs and API key.")
        return
    
    valid_flights = filter_flights_by_lifespan(flights, organ, current_datetime)
    if not valid_flights:
        print(f"No flights found that can transport {organ} within the required time.")
        return
    
    print(f"Found {len(valid_flights)} valid flights.")
    # Now ranking by minimizing remaining lifespan
    top_flights = rank_flights(valid_flights)
    print("\nTop recommended flights:")
    print(format_flight_output(top_flights))


if __name__ == "__main__":
    main()