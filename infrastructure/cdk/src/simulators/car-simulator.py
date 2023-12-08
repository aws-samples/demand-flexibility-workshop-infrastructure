# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
import json
import logging
import requests
import boto3
from datetime import timedelta
from dateutil import parser
import time
from decimal import Decimal
import os

base_url = os.environ["API_URL"]
table_name = os.environ["TABLE_NAME"]
site_wise_info_parameter_name = os.environ["SITEWISE_INFO"]

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(table_name)
cloudwatch = boto3.client("cloudwatch")


def recordCarbonIntensity(charging_status):
    power_rate = 0
    if charging_status:
        # Assuming for now that the car charge is 7kW/h
        # # We operate in 1/2h intervals, so we can just put the current carbon intensity to the metric
        print("car is charging")
        power_rate = 3.5
    else:
        print("not charging")

    base_url = os.environ["API_URL"]
    # The API endpoint
    url = base_url + "/live"

    # A GET request to the API
    response = requests.get(url)

    # Print the response
    live_json = response.json()
    print("live data:")
    print(live_json)

    current_intensity_of_grid = live_json.get("intensity").get("actual")

    print("current_intensity_of_grid")
    print(current_intensity_of_grid)

    # To metric, put the carbon intensity that the aircon is consuming in this interval
    print("Writing {} to CW Metric".format(current_intensity_of_grid * power_rate))
    cloudwatch.put_metric_data(
        Namespace="co2Produced",
        MetricData=[
            {
                "MetricName": "ev_gCO2",
                "Value": current_intensity_of_grid * power_rate,
            }
        ],
    )


def recordComparisonCarbonIntensity(car_away):
    # Funtion only triggered during the unscheduled 6 hours so power rate is fixed
    power_rate = 3.5

    base_url = os.environ["API_URL"]
    # The API endpoint
    url = base_url + "/live"

    # A GET request to the API
    response = requests.get(url)

    # Print the response
    live_json = response.json()
    print("live data:")
    print(live_json)

    current_intensity_of_grid = live_json.get("intensity").get("actual")

    print("current_intensity_of_grid")
    print(current_intensity_of_grid)

    # To metric, put the carbon intensity that the car is consuming in this interval
    if car_away == True:
        cloudwatch.put_metric_data(
            Namespace="co2Produced",
            MetricData=[
                {
                    "MetricName": "no_schedule_ev_gCO2",
                    "Value": 0,
                }
            ],
        )
        print("No Schedule - Car away, writing 0 to CW Metric")
    else:
        cloudwatch.put_metric_data(
            Namespace="co2Produced",
            MetricData=[
                {
                    "MetricName": "no_schedule_ev_gCO2",
                    "Value": current_intensity_of_grid * power_rate,
                }
            ],
        )
        print(
            "No Schedule - Car home, writing {} to CW Metric".format(
                current_intensity_of_grid * power_rate
            )
        )


def getCarCurrentCharge():
    try:
        car_charge = table.get_item(
            Key={"pk": "type#car", "sk": "status#charge"},
        )

        car_current_charge = car_charge["Item"]["charge"]
        print("got car charge")
        print(car_current_charge)

    except Exception as e:
        print(e)
        print("Couldnt find charge, setting it to zero for now.")
        car_current_charge = 0

        response = table.update_item(
            Key={"pk": "type#car", "sk": "status#charge"},
            UpdateExpression="SET charge = if_not_exists(charge, :min)",
            ExpressionAttributeValues={
                ":min": 0,
            },
            # ConditionExpression=condition_expression,
            ReturnValues="UPDATED_NEW",
        )

    return car_current_charge


def updateSitewiseAsset(
    asset_info_json, charge_percent, charging_status, simulation_time_unix_epoch
):
    if (
        asset_info_json["assetId"]
        and asset_info_json["StateOfCharge"]
        and asset_info_json["ChargingStatus"]
    ):
        try:
            # Try to update the sitewise asset
            print("Updating sitewise asset")
            print("State of charge: " + str(int(charge_percent * 100)))
            sitewise_client = boto3.client("iotsitewise")
            response = sitewise_client.batch_put_asset_property_value(
                entries=[
                    {
                        "entryId": "1",
                        "assetId": asset_info_json["assetId"],
                        "propertyId": asset_info_json["StateOfCharge"],
                        "propertyValues": [
                            {
                                "value": {"integerValue": int(charge_percent * 100)},
                                "timestamp": {"timeInSeconds": int(time.time())},
                            },
                        ],
                    },
                    {
                        "entryId": "2",
                        "assetId": asset_info_json["assetId"],
                        "propertyId": asset_info_json["ChargingStatus"],
                        "propertyValues": [
                            {
                                "value": {"booleanValue": charging_status},
                                "timestamp": {"timeInSeconds": int(time.time())},
                            },
                        ],
                    },
                ]
            )
            print(response)
        except Exception as e:
            print(e)
            print("Couldnt update sitewise asset")


def handler(event, context):
    print(("Received event: %s" % json.dumps(event)))

    try:
        # First we want to get the current simulation time
        # If the time is between 8AM and 5:30PM, then we will want to decrease the cars charge
        # If the time is between 5:30PM and 8AM, we will want to check the dynamo schedule for whether the car should be charging right now.

        # First, lets get the time

        # The API endpoint
        url = base_url + "/time"

        # A GET request to the API
        response = requests.get(url)

        get_time_response_json = response.json()

        # Set it to something insane so we can sanity check if something goes wrong. This should be updated further down
        car_charge_increment = -100

        print(get_time_response_json)

        current_datetime = parser.parse(get_time_response_json["time"])

        print("current hour:")
        print(current_datetime.hour)

        # if is_time_between(time(8, 00), time(17, 30), current_datetime):
        if (
            (current_datetime.hour >= 8)
            and (current_datetime.hour < 18)
            and not (current_datetime.hour == 17 and current_datetime.minute == 30)
        ):
            print("Decreasing charge")
            car_charge_increment = -0.05
        else:
            print("Check Schedule")
            # We want to get the date of the evening schedule.
            # This is stored in the table as the date the evening starts

            if 0 <= current_datetime.hour < 8:
                print("time is between midnight and 8AM")
                # Get date of previous day...
                date_object = parser.parse(get_time_response_json["time"])
                day_before_string = str(date_object - timedelta(1))
                print(day_before_string)
                evening_date = day_before_string[:10]
            else:
                print("its between 8AM and midnight")
                evening_date = get_time_response_json["time"][:10]

            print("eveningDate is: " + evening_date)
            schedule_item = table.get_item(
                Key={
                    "sk": "date#" + evening_date,
                    "pk": "type#car",
                }
            )

            if "Item" in schedule_item:
                print("Schedule exists")
                # We have a schedule for the car.
                # Lets check if the car needs to be charging right now.
                print(schedule_item["Item"])

                schedule = schedule_item["Item"]["schedule"]
                # If its not in the schedule, then we dont need to charge.
                car_charge_increment = 0
                for item in schedule:
                    if item["time"] == get_time_response_json["time"]:
                        if item["charging"]:
                            print("Charging!")
                            car_charge_increment = 0.1
                        else:
                            print("not scheduled to charge now, just continue.")
                        break
            else:
                print("couldnt find schedule... hmm ")
                key = json.dumps(
                    {
                        "sk": "date#" + evening_date,
                        "pk": "type#car",
                    }
                )
                print(key)

        # Lets get what the cars current charge is first:
        car_current_charge = getCarCurrentCharge()

        # Now lets update the cars charge
        # We dont want to decrease the cars charge if it is already at 0
        # and we dont want to increase the cars charge if it is already full
        new_charge = car_current_charge + Decimal(str(car_charge_increment))

        charging_status = False

        if new_charge < 0:
            new_charge = 0
            print(
                "Charge not updated as we dont want to decrease the charge if its already at 0"
            )
        if new_charge > 1:
            new_charge = 1
            print(
                "Charge not updated as we dont want to increase the charge if its already full"
            )

        response = table.update_item(
            Key={"pk": "type#car", "sk": "status#charge"},
            UpdateExpression="SET charge = :charge",
            ExpressionAttributeValues={":charge": Decimal(str(new_charge))},
            ReturnValues="UPDATED_NEW",
        )

        ssm_client = boto3.client("ssm")

        parameter = ssm_client.get_parameter(Name=site_wise_info_parameter_name)

        # Check if the parameter values have been updated by the user

        # Translate the value to json
        if car_charge_increment > 0:
            charging_status = True

        sitewise_info_json = json.loads(parameter["Parameter"]["Value"])

        if sitewise_info_json["assetId"] != "UPDATE_ME":
            print("Charge updated")
            updateSitewiseAsset(
                sitewise_info_json,
                charge_percent=new_charge,
                charging_status=charging_status,
                simulation_time_unix_epoch=current_datetime.timestamp(),
            )
        else:
            print("Participant hasn't updated the asset ID, lets skip this for now")

        recordCarbonIntensity(charging_status)

        # Now update the shadow record with the 'do nothing' option of the car just charging as soon as it's plugged in.
        # Assumption is the car will charge as soon as it's plugged in for 6 hours, so 17:30 to 23:30

        if ((current_datetime.hour == 17) and (current_datetime.minute == 30)) or (
            (current_datetime.hour > 17)
            and (current_datetime.hour <= 23)
            or (current_datetime.hour < 8)
        ):
            print("Update the what if record to show CO2 produced with no scheduling")
            recordComparisonCarbonIntensity(car_away=False)
        else:
            recordComparisonCarbonIntensity(car_away=True)

        return get_time_response_json
    except Exception as e:
        logging.error("Exception: %s" % e, exc_info=True)
        return {"error": e}
