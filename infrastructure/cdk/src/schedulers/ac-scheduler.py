# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
import json
import logging
import requests
import boto3
import os


def getDurationValues(forecast_data, start="16:00:00", end="20:00:00") -> list:
    for index_start, item in enumerate(forecast_data):
        if start in item.get("from"):
            break
    else:
        index_start = -1

    for index_end, item in enumerate(forecast_data):
        if end in item.get("from"):
            # We want to ensure the end is after the start
            if index_start < index_end:
                break
    else:
        index_end = -1

    evening_values = forecast_data[index_start:index_end]
    return evening_values


def fahrenheit_to_celsius(temp_f):
    temp_c = (temp_f - 32) * 5 / 9
    return temp_c


def getThisHourTariffPrice(hour, forecast):
    for index, item in enumerate(forecast):
        if hour in item["from"]:
            return item["tariff"]["import"]
    return "error, couldnt find tariff price"


def getThisHourTempChange(hour):
    if (1 == hour) or (3 <= hour < 5) or (18 <= hour < 20):
        temp_increment = -1
    elif (hour == 0) or (5 == hour) or (16 <= hour < 18) or (23 == hour):
        temp_increment = 0
    elif (6 <= hour < 9) or (12 <= hour < 16):
        temp_increment = 1
    elif hour == 9:
        temp_increment = 3
    elif hour == 2:
        temp_increment = -3
    elif 10 <= hour < 12:
        temp_increment = 2
    else:
        temp_increment = -2

    return temp_increment


def getAverageTariffPrice(forecast):
    averageValue = sum(c["tariff"]["import"] for c in forecast) / len(forecast)
    print("getAverageTariffPrice")
    print(averageValue)
    return averageValue


def handler(event, context):
    print(("Received event: %s" % json.dumps(event)))
    try:
        # ********************** API call to get the forecast data **********************

        base_url = os.environ["API_URL"]
        table_name = os.environ["TABLE_NAME"]
        # The API endpoint
        url = base_url + "/tariff-forecast"

        # A GET request to the API
        response = requests.get(url)

        # Print the response
        forecast_json = response.json()

        print("Forecast JSON:")
        print(forecast_json)

        # ********************** Calculate our cooling schedule **********************

        # We now have the tariff forecast for the next 24 hours.

        # Same as module 1, we leave the house at 8AM every day, and get back home at 17:30PM.

        # At this time of year, our house has an average temp gain as follows (in degrees C)
        # | Hour | Temp Change | No AC Temperature (C) |
        # |------|-------------|-------------|
        # | 0    | 0           | 24          |
        # | 1    | -1          | 23          |
        # | 2    | -3          | 20          |
        # | 3    | -1          | 19          |
        # | 4    | -1          | 18          |
        # | 5    | 0           | 18          |
        # | 6    | 1           | 19          |
        # | 7    | 1           | 20          |
        # | 8    | 1           | 21          |
        # | 9    | 3           | 24          |
        # | 10   | 2           | 26          |
        # | 11   | 2           | 28          |
        # | 12   | 1           | 29          |
        # | 13   | 1           | 30          |
        # | 14   | 1           | 31          |
        # | 15   | 1           | 32          |
        # | 16   | 0           | 32          |
        # | 17   | 0           | 32          |
        # | 18   | -1          | 31          |
        # | 19   | -1          | 30          |
        # | 20   | -2          | 28          |
        # | 21   | -2          | 26          |
        # | 22   | -2          | 24          |
        # | 23   | 0           | 24          |

        # We've provided a function that will return the temp change for a given hour: getThisHourTempChange(hour)

        # At the moment, we have our AC on from the hours of 4PM and 9PM
        # Our AC cools at a rate of -3 degrees C an hour.

        # For the sake of the simulation, lets say that the temperate changes still happen
        # no matter what the temperature inside the house is

        # First, lets set the temperature that we want our house to be when we get home in the evening.

        # For folk who use fahrenheit, we've provided a function for you to convert to celsius:
        # ideal_temperature_celsius = fahrenheit_to_celsius(71)
        # Please use this function throughout if you'd like

        # To make it easier for you, at midnight every night, the house is always 24 degrees celsius.
        ideal_temperature_celsius = 24

        averageTariffPrice = getAverageTariffPrice(forecast_json)

        # This is where our schedule is being written- might be a good place to start changing things!

        # At the moment we're just charging constantly between 4PM to 8PM. This doesnt seem ideal!
        forecast_duration = getDurationValues(
            forecast_data=forecast_json, start="16:00:00", end="20:00:00"
        )

        schedule = []

        for item in forecast_duration:
            # We've got a function which gets the tariff price for a given hour:
            # getThisHourTariffPrice(item["from"], forecast_json)
            # Might be useful!
            schedule.append({"time": item["from"], "cooling": True})

        # ********************** Put our schedule in dynamodb **********************

        # Let's extract the date that our schedule will be for so we can use it as ID in our table
        # We know it'll be in ISO string format, so we can just substring the first 10 characters
        forecast_date = forecast_duration[0]["from"][:10]

        # Now lets put the schedule in dynamodb

        # We'll use the management table
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(table_name)
        table.put_item(
            Item={
                "sk": "date#" + forecast_date,
                "pk": "type#ac",
                "schedule": schedule,
            }
        )

        print("AC schedule:")
        print(schedule)
        return schedule

    except Exception as e:
        logging.error("Exception: %s" % e, exc_info=True)
        return e
