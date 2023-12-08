#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { GrafanaStack  } from '../lib/grafana-stack';
import { DeviceSimulationStack } from '../lib/device-simulation-stack';
import { TwinmakerStack } from '../lib/twinmaker-stack';
import { AwsSolutionsChecks } from 'cdk-nag'
import { Aspects } from 'aws-cdk-lib';

const app = new cdk.App();

const OWNER = app.node.tryGetContext("owner");

Aspects.of(app).add(new AwsSolutionsChecks({ verbose: true }))

const grafanaStack = new GrafanaStack(app, OWNER+'-GrafanaStack', {
  grafanaPassword: "reinvent2023",
  grafanaUsername: "demand-flex",
  owner: OWNER
});

new DeviceSimulationStack(app, OWNER+'-DeviceSimulationStack', { owner: OWNER})

new TwinmakerStack(app, OWNER+'-TwinmakerStack', { owner: OWNER, grafanaTask: grafanaStack.grafanaTask, grafanaDomain: grafanaStack.grafanaDomain, logBucket: grafanaStack.logBucket})




