import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as ecsPatterns from "aws-cdk-lib/aws-ecs-patterns";
import * as logs from "aws-cdk-lib/aws-logs";
import * as cloudfront from "aws-cdk-lib/aws-cloudfront";
import * as cloudfrontOrigins from "aws-cdk-lib/aws-cloudfront-origins";
import * as path from "path";
import * as fs from "fs";
import { NagSuppressions } from "cdk-nag";
import {
  Bucket,
  BlockPublicAccess,
  BucketEncryption,
  ObjectOwnership
} from "aws-cdk-lib/aws-s3";
import { log } from "console";

interface GrafanaStackProps extends cdk.StackProps {
  grafanaUsername: string;
  grafanaPassword: string;
  owner: string;
}
export class GrafanaStack extends cdk.Stack {
  public readonly grafanaTask: ecs.FargateTaskDefinition;
  public readonly grafanaDomain: string;
  public readonly logBucket: Bucket;

  constructor(scope: Construct, id: string, props: GrafanaStackProps) {
    super(scope, id);

    const owner = props.owner + "-";

    const logBucket = new Bucket(this, `${owner}demandflex-log-bucket`, {
      bucketName: `${this.account}-${owner}demandflex-log-bucket`,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      encryption: BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      objectOwnership: ObjectOwnership.BUCKET_OWNER_ENFORCED,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    NagSuppressions.addResourceSuppressions(logBucket, [
      {
        id: "AwsSolutions-S1",
        reason: "This is the log bucket",
      },
    ]);

    const vpc = new ec2.Vpc(this, owner + "GrafanaVPC", {
      natGateways: 1,
    });

    vpc.addFlowLog("FlowLogCloudwatch", {});

    const cluster = new ecs.Cluster(this, owner + "GrafanaCluster", {
      vpc,
      containerInsights: true,
    });

    const provisionScriptPayload = fs.readFileSync(
      path.join(__dirname, "..", "grafana", "provision.sh"),
      "utf-8"
    );

    // let dashboardPayload = fs.readFileSync(
    //   path.join(__dirname, "..", "grafana", "dashboard.json"),
    //   "utf-8"
    // );
    // dashboardPayload = JSON.stringify(JSON.parse(dashboardPayload));

    const taskDefinition = new ecs.FargateTaskDefinition(
      this,
      owner + "GrafanaTaskDefinition",
      {
        cpu: 512,
        memoryLimitMiB: 2048,
      }
    );
    taskDefinition.addContainer("grafana", {
      image: ecs.ContainerImage.fromRegistry(
        "public.ecr.aws/bitnami/grafana:9-debian-11"
      ),
      essential: true,
      portMappings: [
        {
          containerPort: 3000,
        },
      ],
      environment: {
        GF_SECURITY_ADMIN_USER: props.grafanaUsername,
        GF_SECURITY_ADMIN_PASSWORD: props.grafanaPassword,
        GF_INSTALL_PLUGINS:'grafana-iot-twinmaker-app:1.9.2,marcusolsson-json-datasource:1.3.8',
        AWS_REGION: this.region,
        PROVISION: provisionScriptPayload,
        // DASHBOARD: dashboardPayload,
      },
      entryPoint: ["/bin/bash"],
      command: ["-c", 'eval "$PROVISION"'],
      logging: new ecs.AwsLogDriver({
        streamPrefix: "GrafanaService",
        logRetention: logs.RetentionDays.ONE_WEEK,
      }),
    });

    NagSuppressions.addResourceSuppressions(taskDefinition, [
      {
        id: "AwsSolutions-ECS2",
        reason:
          "We are not putting the environment variables in secrets manager, disagree with this in the first place",
      },
    ]);

    const service = new ecsPatterns.ApplicationLoadBalancedFargateService(
      this,
      owner + "Service",
      {
        cluster,
        desiredCount: 1,
        loadBalancerName: owner + "GrafanaALB",
        taskDefinition,
      }
    );

    NagSuppressions.addResourceSuppressions(service.loadBalancer, [
      {
        id: "AwsSolutions-ELB2",
        reason: "Access logs cant be enabled on region agnostic stacks",
      },
    ]);

    service.targetGroup.configureHealthCheck({
      path: "/api/health",
    });

    // Remove unwanted Outputs
    try {
      service.node.tryRemoveChild("LoadBalancerDNS");
      service.node.tryRemoveChild("ServiceURL");
    } catch (e) {
      console.log("WARN: failed to clean CloudFormation Outputs:", e);
    }

    NagSuppressions.addStackSuppressions(this, [
      {
        id: "AwsSolutions-EC23",
        reason:
          "We are opening this to 0.0.0.0/0 because they are meant to be publically accessible. The boards are username/password protected.",
      },
    ]);

    const distribution = new cloudfront.Distribution(
      this,
      owner + "GrafanaDistribution",
      {
        defaultBehavior: {
          origin: new cloudfrontOrigins.LoadBalancerV2Origin(
            service.loadBalancer,
            {
              protocolPolicy: cloudfront.OriginProtocolPolicy.HTTP_ONLY,
            }
          ),
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
          viewerProtocolPolicy:
            cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER,
        },
        minimumProtocolVersion: cloudfront.SecurityPolicyProtocol.TLS_V1_2_2018,
      }
    );

    NagSuppressions.addResourceSuppressions(distribution, [
      {
        id: "AwsSolutions-CFR4",
        reason:
          "I've added in the TLS version, not sure why this is still coming up",
      },
    ]);

    NagSuppressions.addResourceSuppressions(distribution, [
      {
        id: "AwsSolutions-CFR5",
        reason:
          "I've added in the TLS version, not sure why this is still coming up",
      },
    ]);

    NagSuppressions.addResourceSuppressions(distribution, [
      {
        id: "AwsSolutions-CFR3",
        reason:
          "I've added in the TLS version, not sure why this is still coming up",
      },
    ]);

    new cdk.CfnOutput(this, owner + "GrafanaURL", {
      value: `https://${distribution.domainName}`,
    });

    this.grafanaTask = taskDefinition;
    this.grafanaDomain = distribution.domainName;
    this.logBucket = logBucket;

    NagSuppressions.addStackSuppressions(this, [
      {
        id: "AwsSolutions-IAM5",
        reason: "We need star to allow access to write to logs",
      },
    ]);
  }
}
