import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import { Runtime, Architecture, LayerVersion, Code } from "aws-cdk-lib/aws-lambda";
import { Rule, Schedule } from "aws-cdk-lib/aws-events";
import { LambdaFunction } from "aws-cdk-lib/aws-events-targets";
import { Table, AttributeType } from "aws-cdk-lib/aws-dynamodb";
import { PythonFunction } from "@aws-cdk/aws-lambda-python-alpha";
import { StringParameter } from "aws-cdk-lib/aws-ssm";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import { NagSuppressions } from 'cdk-nag'

interface DeviceSimulationProps extends cdk.StackProps {
  owner: string;
}
export class DeviceSimulationStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: DeviceSimulationProps) {
    super(scope, id, props);

    const owner = props.owner + "-";
    const apiURL = "https://alkg4x7726.execute-api.us-east-1.amazonaws.com/dev";

    const pythonLayer = new LayerVersion(this, 'shared-layer', {
      code: Code.fromAsset('layer'),
      compatibleRuntimes: [Runtime.PYTHON_3_11],
      layerVersionName: 'shared-layer',
    })

    const managementTable = new Table(this, owner + "managementTable", {
      tableName: owner + "managementTable",
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      partitionKey: {
        name: "pk",
        type: AttributeType.STRING,
      },
      sortKey: {
        name: "sk",
        type: AttributeType.STRING,
      },
    });

    const simulatorTrigger = new Rule(this, owner + "simulation-rule", {
      schedule: Schedule.expression("rate(1 minute)"),
    });

    const ssmCarSitewiseParameter = new StringParameter(
      this,
      owner + "car-sitewise-connector",
      {
        parameterName: owner + "car-sitewise-connector",
        stringValue:
          '{"assetId": "UPDATE_ME", "ChargingStatus": "UPDATE_ME", "StateOfCharge": "UPDATE_ME"}',
      }
    );

    const ssmACSitewiseParameter = new StringParameter(
      this,
      owner + "ac-sitewise-connector",
      {
        parameterName: owner + "ac-sitewise-connector",
        stringValue:
          '{"assetId": "UPDATE_ME", "CurrentTemperature": "UPDATE_ME", "Status": "UPDATE_ME"}',
      }
    );

    const carSimulatorLambda = new PythonFunction(this, owner + "carSimulator", {
      entry: "src/simulators",
      runtime: Runtime.PYTHON_3_11,
      architecture: Architecture.ARM_64,
      functionName: owner + "CarSimulatorFunction",
      index: "car-simulator.py",
      timeout: cdk.Duration.seconds(500),
      environment: {
        TABLE_NAME: managementTable.tableName,
        API_URL: apiURL,
        SITEWISE_INFO: ssmCarSitewiseParameter.parameterName,
      },
      layers: [pythonLayer],
    });

    ssmCarSitewiseParameter.grantRead(carSimulatorLambda);

    carSimulatorLambda.addToRolePolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: [
          "iotsitewise:BatchPutAssetPropertyValue",
          "iotsitewise:Describe*",
          "iotsitewise:Get*",
          "iotsitewise:List*",
          "cloudwatch:PutMetric*"
        ],
        resources: ["*"],
      })
    );

    const acSimulatorLambda = new PythonFunction(
      this,
      owner + "ACSimulator",
      {
        entry: "src/simulators",
        runtime: Runtime.PYTHON_3_11,
        architecture: Architecture.ARM_64,
        functionName: owner + "ACSimulatorFunction",
        index: "ac-simulator.py",
        timeout: cdk.Duration.seconds(500),
        environment: {
          TABLE_NAME: managementTable.tableName,
          API_URL: apiURL,
          SITEWISE_INFO: ssmACSitewiseParameter.parameterName,
        },
        layers: [pythonLayer],
      }
    );

    acSimulatorLambda.addToRolePolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: [
          "iotsitewise:BatchPutAssetPropertyValue",
          "iotsitewise:Describe*",
          "iotsitewise:Get*",
          "iotsitewise:List*",
          "cloudwatch:PutMetric*"
        ],
        resources: ["*"],
      })
    );

    ssmACSitewiseParameter.grantRead(acSimulatorLambda);

    simulatorTrigger.addTarget(new LambdaFunction(carSimulatorLambda, {}));
    simulatorTrigger.addTarget(new LambdaFunction(acSimulatorLambda, {}));

    const participantCarLambda = new PythonFunction(
      this,
      owner + "Car-Scheduler",
      {
        entry: "src/schedulers",
        functionName: owner + "CarSchedulingFunction",
        runtime: Runtime.PYTHON_3_11,
        architecture: Architecture.ARM_64,
        index: "car-scheduler.py",
        timeout: cdk.Duration.seconds(500),
        environment: {
          TABLE_NAME: managementTable.tableName,
          API_URL: apiURL,
        },
        layers: [pythonLayer],
      }
    );

    participantCarLambda.addToRolePolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: [
          "iotsitewise:Describe*",
          "iotsitewise:Get*",
          "iotsitewise:List*",
        ],
        resources: ["*"],
      })
    );

    simulatorTrigger.addTarget(new LambdaFunction(participantCarLambda, {}));

    const participantACLambda = new PythonFunction(
      this,
      owner + "AC-Scheduler",
      {
        entry: "src/schedulers",
        functionName: owner + "ACSchedulingFunction",
        runtime: Runtime.PYTHON_3_11,
        architecture: Architecture.ARM_64,
        index: "ac-scheduler.py",
        timeout: cdk.Duration.seconds(500),
        environment: {
          TABLE_NAME: managementTable.tableName,
          API_URL: apiURL,
        },
        layers: [pythonLayer],
      }
    );

    participantACLambda.addToRolePolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: [
          "iotsitewise:Describe*",
          "iotsitewise:Get*",
          "iotsitewise:List*",
        ],
        resources: ["*"],
      })
    );

    simulatorTrigger.addTarget(new LambdaFunction(participantACLambda, {}))


    managementTable.grantReadWriteData(participantCarLambda);
    managementTable.grantReadWriteData(carSimulatorLambda);
    managementTable.grantReadWriteData(participantACLambda);
    managementTable.grantReadWriteData(acSimulatorLambda);

    NagSuppressions.addStackSuppressions(this, [
      {
        id: 'AwsSolutions-IAM5',
        reason: 'We need star to allow access to write to logs'
      },
    ])

    NagSuppressions.addStackSuppressions(this, [
      {
        id: 'AwsSolutions-IAM4',
        reason: 'We need lambda basic execution policy'
      },
    ])

  }
}
