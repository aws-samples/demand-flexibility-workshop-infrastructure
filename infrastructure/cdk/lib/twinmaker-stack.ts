import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import { CfnWorkspace, CfnEntity } from "aws-cdk-lib/aws-iottwinmaker";
import {
  Bucket,
  BlockPublicAccess,
  BucketEncryption,
  HttpMethods,
} from "aws-cdk-lib/aws-s3";
import {
  Role,
  ServicePrincipal,
  PolicyStatement,
  Effect,
  PolicyDocument,
} from "aws-cdk-lib/aws-iam";
import { FargateTaskDefinition } from "aws-cdk-lib/aws-ecs";
import { NagSuppressions } from "cdk-nag";


interface TwinmakerStackProps extends cdk.StackProps {
  owner: string;
  grafanaTask: FargateTaskDefinition;
  grafanaDomain: string;

  logBucket: Bucket
}
export class TwinmakerStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: TwinmakerStackProps) {
    super(scope, id);

    const owner = props.owner + "-";

    const bucket = new Bucket(this, `${owner}twinmaker-bucket`, {
      bucketName: `${this.account}-${owner}twinmaker-bucket`,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      encryption: BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      serverAccessLogsBucket: props.logBucket,
      cors: [
        {
          allowedMethods: [
            HttpMethods.GET,
            HttpMethods.DELETE,
            HttpMethods.PUT,
            HttpMethods.HEAD,
            HttpMethods.POST,
          ],
          allowedOrigins: [`*${props.grafanaDomain}`],
          allowedHeaders: ["*"],
          exposedHeaders: ["ETag"],
        },
      ],
    });

    const workspaceS3PolicyStatement = new PolicyStatement({
      effect: Effect.ALLOW,
      resources: [bucket.bucketArn, bucket.bucketArn + "/*"],
      actions: [
        "s3:GetBucket*",
        "s3:GetObject",
        "s3:ListBucket",
        "s3:PutObject",
      ],
    });

    const workspaceS3DeletePolicyStatement = new PolicyStatement({
      effect: Effect.ALLOW,
      resources: ["arn:aws:s3:::*/DO_NOT_DELETE_WORKSPACE_*"],
      actions: ["s3:DeleteObject"],
    });

    const workspaceSitewisePolicyStatement = new PolicyStatement({
      effect: Effect.ALLOW,
      resources: [
        "arn:aws:iotsitewise:*:*:asset-model/*",
        "arn:aws:iotsitewise:*:*:asset/*",
      ],
      actions: [
        "iotsitewise:GetPropertyValueHistory",
        "iotsitewise:BatchPutPropertyValues",
        "iotsitewise:DescribeAsset",
        "iotsitewise:GetAssetPropertyValue",
        "iotsitewise:DescribeAssetModel",
        "iotsitewise:GetAssetPropertyValueHistory",
      ],
    });

    const workspaceSitewisePolicy = new PolicyDocument({
      statements: [
        workspaceSitewisePolicyStatement,
        workspaceS3DeletePolicyStatement,
        workspaceS3PolicyStatement,
      ],
    });

    const workspaceRole = new Role(this, "workspaceRole", {
      assumedBy: new ServicePrincipal("iottwinmaker.amazonaws.com"),
      description: "Twinmaker workspace role",
      inlinePolicies: { workspaceSitewisePolicy },
    });

    const cfnWorkspace = new CfnWorkspace(this, `${owner}twinmaker-workspace`, {
      role: workspaceRole.roleArn,
      s3Location: bucket.bucketArn,
      workspaceId: `${owner}demandflex-workspace`,
      description: "Workspace to host our assets for the demand flex workshop",
    });

    cfnWorkspace.node.addDependency(workspaceRole);
    cfnWorkspace.node.addDependency(bucket);

    const cfnEVEntity = new CfnEntity(this, "EVEntity", {
      entityName: `${owner}EVEntity`,
      workspaceId: `${owner}demandflex-workspace`,
    });

    const cfnACEntity = new CfnEntity(this, "ACEntity", {
      entityName: `${owner}ACEntity`,
      workspaceId: `${owner}demandflex-workspace`,
    });

    cfnEVEntity.node.addDependency(cfnWorkspace);
    cfnACEntity.node.addDependency(cfnWorkspace);

    const dataSourceS3PolicyStatement = new PolicyStatement({
      effect: Effect.ALLOW,
      resources: [bucket.bucketArn, bucket.bucketArn + "/*"],
      actions: ["s3:GetObject"],
    });

    const dataSourceS3PolicyStatement2 = new PolicyStatement({
      effect: Effect.ALLOW,
      resources: [bucket.bucketArn, bucket.bucketArn + "/*"],
      actions: ["s3:GetObject"],
    });

    const dataSourceCloudWatchMetricsPolicyStatement = new PolicyStatement({
      effect: Effect.ALLOW,
      resources: ["*"],
      actions: [
        "cloudwatch:DescribeAlarmsForMetric",
        "cloudwatch:DescribeAlarmHistory",
        "cloudwatch:DescribeAlarms",
        "cloudwatch:ListMetrics",
        "cloudwatch:GetMetricData",
        "cloudwatch:GetInsightRuleReport",
      ],
    });

    const dataSourceCloudWatchLogsPolicyStatement = new PolicyStatement({
      effect: Effect.ALLOW,
      resources: ["*"],
      actions: [
        "logs:DescribeLogGroups",
        "logs:GetLogGroupFields",
        "logs:StartQuery",
        "logs:StopQuery",
        "logs:GetQueryResults",
        "logs:GetLogEvents",
      ],
    });

    const datasourcewWorkspacePolicyStatement = new PolicyStatement({
      effect: Effect.ALLOW,
      resources: [cfnWorkspace.attrArn, cfnWorkspace.attrArn + "/*"],
      actions: ["iottwinmaker:Get*", "iottwinmaker:List*"],
    });

    const datasourcewListWorkspacePolicyStatement = new PolicyStatement({
      effect: Effect.ALLOW,
      resources: ["*"],
      actions: ["iottwinmaker:ListWorkspaces"],
    });

    const grafanaDatasourcePolicy = new PolicyDocument({
      statements: [
        dataSourceS3PolicyStatement,
        datasourcewWorkspacePolicyStatement,
        datasourcewListWorkspacePolicyStatement,
        workspaceSitewisePolicyStatement,
        workspaceS3DeletePolicyStatement,
        workspaceS3PolicyStatement,
        dataSourceCloudWatchMetricsPolicyStatement,
        dataSourceCloudWatchLogsPolicyStatement,
      ],
    });

    const datasourceRole = new Role(this, `${owner}grafana-datasource-role`, {
      roleName: `${owner}grafana-datasource-role`,
      assumedBy: props.grafanaTask.taskRole,
      inlinePolicies: { grafanaDatasourcePolicy },
    });

    // output the datasource role to cloudformation outputs
    new cdk.CfnOutput(this, `${owner}grafana-datasource-role-arn`, {
      value: datasourceRole.roleArn,
      description: "Grafana Datasource Role Arn",
      exportName: `${owner}grafana-datasource-role-arn`,
    });

    props.grafanaTask.addToTaskRolePolicy(workspaceSitewisePolicyStatement);
    props.grafanaTask.addToTaskRolePolicy(
      dataSourceCloudWatchMetricsPolicyStatement
    );
    props.grafanaTask.addToTaskRolePolicy(
      dataSourceCloudWatchLogsPolicyStatement
    );

    NagSuppressions.addStackSuppressions(this, [
      {
        id: "AwsSolutions-IAM5",
        reason: "We need star to allow access to write to logs",
      },
    ]);
  }
}
