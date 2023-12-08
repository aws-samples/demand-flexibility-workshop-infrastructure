# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
import json
import logging
import requests
import boto3
import datetime, time
from dateutil import parser
from decimal import Decimal
import os

base_url = os.environ["API_URL"]
table_name = os.environ["TABLE_NAME"]
site_wise_info_parameter_name = os.environ["SITEWISE_INFO"]

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(table_name)
sitewise_client = boto3.client("iotsitewise")
cloudwatch = boto3.client("cloudwatch")


def updateSitewiseAsset(asset_info_json, temperature, status):
    if (
        asset_info_json["assetId"]
        and asset_info_json["CurrentTemperature"]
        and asset_info_json["Status"]
    ):
        try:
            # Try to update the sitewise asset
            print("Updating sitewise asset")
            print("Current Temp: " + str(temperature))
            temp = float(temperature)
            # print(temp)
            response = sitewise_client.batch_put_asset_property_value(
                entries=[
                    {
                        "entryId": "1",
                        "assetId": asset_info_json["assetId"],
                        "propertyId": asset_info_json["CurrentTemperature"],
                        "propertyValues": [
                            {
                                "value": {"doubleValue": temp},
                                "timestamp": {"timeInSeconds": int(time.time())},
                            },
                        ],
                    },
                    {
                        "entryId": "2",
                        "assetId": asset_info_json["assetId"],
                        "propertyId": asset_info_json["Status"],
                        "propertyValues": [
                            {
                                "value": {"booleanValue": status},
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


def recordCarbonIntensity(ac_on):
    power_rate = 0
    if ac_on:
        print("ac is on")
        # 4kw/h
        power_rate = 2
    else:
        print("ac is off")
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

    # Assuming for now that the aircon is 4kW/h

    # We operate in 1/2h intervals, so we can just put the current carbon intensity to the metric

    # To metric, put the carbon intensity that the aircon is consuming in this interval

    cloudwatch.put_metric_data(
        Namespace="co2Produced",
        MetricData=[
            {
                "MetricName": "ac_gCO2",
                "Value": current_intensity_of_grid * power_rate,
            }
        ],
    )


def recordComparisonCarbonIntensity(ac_on):
    # Assuming for now that the aircon is 4kW/h at full power
    power_rate = 2

    if ac_on:
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

        cloudwatch.put_metric_data(
            Namespace="co2Produced",
            MetricData=[
                {
                    "MetricName": "no_schedule_ac_gCO2",
                    "Value": current_intensity_of_grid * power_rate,
                }
            ],
        )
    else:
        cloudwatch.put_metric_data(
            Namespace="co2Produced",
            MetricData=[
                {
                    "MetricName": "no_schedule_ac_gCO2",
                    "Value": 0,
                }
            ],
        )


def handler(event, context):
    print(("Received event: %s" % json.dumps(event)))

    try:
        # First we want to get the current simulation time
        # First, lets get the time

        # The API endpoint
        url = base_url + "/time"

        # A GET request to the API
        response = requests.get(url)

        get_time_response_json = response.json()

        # Set it to something insane so we can sanity check if something goes wrong. This should be updated further down
        temp_increment = -100

        print(get_time_response_json)

        current_datetime = parser.parse(get_time_response_json["time"])

        print("current hour:")
        print(current_datetime.hour)

        # Get Current Temp
        current_temp = None

        if current_datetime.hour == 0:
            # reset our temp back to what it needs to be at the start
            current_temp = 24
        elif (
            (1 == current_datetime.hour)
            or (3 <= current_datetime.hour < 5)
            or (18 <= current_datetime.hour < 20)
        ):
            temp_increment = -0.5
        elif (
            (5 == current_datetime.hour)
            or (16 <= current_datetime.hour < 18)
            or (23 == current_datetime.hour)
        ):
            temp_increment = 0
        elif (6 <= current_datetime.hour < 9) or (12 <= current_datetime.hour < 16):
            temp_increment = 0.5
        elif current_datetime.hour == 9:
            temp_increment = 1.5
        elif current_datetime.hour == 2:
            temp_increment = -1.5
        elif 10 <= current_datetime.hour < 12:
            temp_increment = 1
        else:
            temp_increment = -1

        print("Check Schedule")

        # We want to get the date of todays schedule.

        todays_date = get_time_response_json["time"][:10]

        print("todays_date is: " + todays_date)
        schedule_item = table.get_item(
            Key={
                "sk": "date#" + todays_date,
                "pk": "type#ac",
            }
        )

        ac_on = False
        if "Item" in schedule_item:
            print("Cooling schedule exists")
            # We have a schedule for the car.
            # Lets check if the car needs to be charging right now.
            print(schedule_item["Item"])

            schedule = schedule_item["Item"]["schedule"]
            # If its not in the schedule, then we dont need to cool.
            for item in schedule:
                if item["time"] == get_time_response_json["time"]:
                    if item["cooling"]:
                        print("cooling!")
                        ac_on = True
                        temp_increment -= 1.5
                    else:
                        print("not scheduled to cool now, just continue.")
                    break
        else:
            print("couldnt find schedule... hmm ")
            key = json.dumps(
                {
                    "sk": "date#" + todays_date,
                    "pk": "type#ac",
                }
            )
            print(key)

        if current_temp is not None:
            print("setting manual temp!")
            response = table.update_item(
                Key={"pk": "type#house", "sk": "status#temperature"},
                UpdateExpression="SET temperature = :newtemp, day_hour = :day_hour",
                ExpressionAttributeValues={
                    ":newtemp": current_temp,
                    ":day_hour": current_datetime.hour,
                },
                ReturnValues="UPDATED_NEW",
            )
        else:
            response = table.update_item(
                Key={"pk": "type#house", "sk": "status#temperature"},
                UpdateExpression="SET temperature = if_not_exists(temperature, :min) + :inc, day_hour = :day_hour",
                ExpressionAttributeValues={
                    ":inc": Decimal(str(temp_increment)),
                    ":min": 24,
                    ":day_hour": current_datetime.hour,
                },
                ReturnValues="UPDATED_NEW",
            )

        ssm_client = boto3.client("ssm")

        parameter = ssm_client.get_parameter(Name=site_wise_info_parameter_name)

        # Check if the parameter values have been updated by the user

        # Calculate carbon intensity
        recordCarbonIntensity(ac_on)

        # Translate the value to json

        sitewise_info_json = json.loads(parameter["Parameter"]["Value"])

        if sitewise_info_json["assetId"] != "UPDATE_ME":
            print("temperature updated")
            # Get the latest temperature from the dynamo table
            if current_temp is None:
                try:
                    current_temp_item = table.get_item(
                        Key={"pk": "type#house", "sk": "status#temperature"}
                    )
                    current_temp = current_temp_item["Item"]["temperature"]
                except Exception as e:
                    print(e)
                    print("Couldnt find temperature, setting it to 24 for now.")
                    current_temp = 24

            updateSitewiseAsset(
                sitewise_info_json,
                temperature=current_temp,
                status=ac_on,
                # simulation_time_unix_epoch=current_datetime.timestamp(),
            )
        else:
            print("Participant hasnt updated the asset ID, lets skip this for now")

        if (current_datetime.hour >= 16) and (current_datetime.hour < 20):
            print("Update the what if record to show CO2 produced with no scheduling")
            recordComparisonCarbonIntensity(ac_on=True)
        else:
            recordComparisonCarbonIntensity(ac_on=False)

        return get_time_response_json
    except Exception as e:
        logging.error("Exception: %s" % e, exc_info=True)
        return {"error": e}
