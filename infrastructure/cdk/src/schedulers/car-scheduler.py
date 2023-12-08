# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
import json
import logging
import requests
import boto3
import os


def getOvernightValues(forecast_data):
    string530pm = "17:30:00"
    string8am = "08:00:00"

    for index_530, item in enumerate(forecast_data):
        if string530pm in item.get("from"):
            break
    else:
        index_530 = -1

    for index_8, item in enumerate(forecast_data):
        if string8am in item.get("from"):
            # We want to ensure the 8AM is the one after the next 530PM
            if index_530 < index_8:
                break
    else:
        index_8 = -1

    night_values = forecast_data[index_530:index_8]

    return night_values


def handler(event, context):
    print(("Received event: %s" % json.dumps(event)))
    try:
        # ********************** API call to get the forecast data **********************

        base_url = os.environ["API_URL"]
        table_name = os.environ["TABLE_NAME"]
        # The API endpoint
        url = base_url + "/intensity-forecast"

        # A GET request to the API
        response = requests.get(url)

        # Print the response
        forecast_json = response.json()

        print("Forecast JSON:")
        print(forecast_json)

        # ********************** Calculate our charging schedule **********************

        # We now have the carbon intensity forecast for the next 24 hours.
        # We'll want to create a schedule to ensure we're charging our EV to full only using the energy with the lowest carbon intensity
        # And we need our car to be fully charged by the time we head off to work at 8:00AM
        # We come back home at 5:30PM every day.
        # For the purposes of this exercise we'll assume that we have the same exact schedule on the weekends while we're out having fun.

        # Our car charges at a rate of 17% per hour. This means we need to charge for at most 6 whole hours overnight.
        # Our data is in half hour intervals, and there are 14.5 hours, or 29 half hour intervals which we can choose from.
        # So we need to identify the 12 half hour intervals with the lowest carbon intensity over hour the 29 options we have!

        # First lets get a subset of the forecast from 5:30PM to 8:00AM

        night_values = getOvernightValues(forecast_json)

        # TODO we only want to be charging for 12 half hours total, instead of the whole night
        # How should we select the 12 half hour intervals for the schedule
        # if we want to ensure the energy with the lowest carbon intensity is used?

        # This is our blank charging schedule that we need to complete so that our car can charge overnight.
        schedule = []

        # For every hour overnight, we are currently always charging.
        for item in night_values:
            # This is where our schedule is being written to- might be a good place to start changing things!

            # Tip: Please keep this schedule format when you write your code! This is the format the dynamo db table needs.
            schedule.append({"time": item["from"], "charging": True})


        # Stretch goal: We're assuming here that our car is always returned empty and always needs a full 6h of charge every night.
        # We are assuming its always at 0 when we return home.
        # How can we optimize this so that we only charge what we need?

        # If you've got your schedule in the format as defined above, you shouldn't need to edit anything below this line.
        # ********************** Put our schedule in dynamodb **********************

        # Let's extract the date that our schedule will be for so we can use it as ID in our table
        # We know it'll be in ISO string format, so we can just substring the first 10 characters
        eveningDate = night_values[0]["from"][:10]

        # Now lets put the schedule in dynamodb

        # We'll use the car-scheduler-table as the table
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(table_name)
        table.put_item(
            Item={"sk": "date#" + eveningDate, "pk": "type#car", "schedule": schedule}
        )

        print("Charging schedule:")
        print(schedule)
        return schedule

    except Exception as e:
        logging.error("Exception: %s" % e, exc_info=True)
        return e
