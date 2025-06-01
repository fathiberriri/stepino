from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_efs as efs,
    aws_iam as iam,   
    RemovalPolicy,
    Tags,
)
from constructs import Construct

class SimpleEfsStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, project: str, environment: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # 1. VPC with private subnets
        vpc = ec2.Vpc(self, "Vpc",
            max_azs=2,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24
                )
            ]
        )
        Tags.of(vpc).add("Name", f"{project}-{environment}-vpc")

        # 2. Security group for EC2 and EFS
        ec2_sg = ec2.SecurityGroup(self, "Ec2SG", vpc=vpc, description="EC2 SG")
        efs_sg = ec2.SecurityGroup(self, "EfsSG", vpc=vpc, description="EFS SG")
        # Allow EC2 to connect to EFS on NFS port
        efs_sg.add_ingress_rule(ec2_sg, ec2.Port.tcp(2049), "Allow NFS from EC2")

        # 3. EFS file system in private subnets
        file_system = efs.FileSystem(self, "EfsFileSystem",
                vpc=vpc,
                security_group=efs_sg,
                removal_policy=RemovalPolicy.DESTROY,
                vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
                file_system_policy=iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "elasticfilesystem:ClientMount",
                                "elasticfilesystem:ClientWrite",
                                "elasticfilesystem:ClientRootAccess"
                            ],
                            principals=[iam.AnyPrincipal()],
                            conditions={
                                "Bool": {"elasticfilesystem:AccessedViaMountTarget": "true"}
                            }
                        )
                    ]
                )
        )
        Tags.of(file_system).add("Name", f"{project}-{environment}-efs")

        # 4. User data to mount EFS
        user_data = ec2.UserData.for_linux()
        user_data.add_commands(
            "yum update -y",
            "yum install -y amazon-efs-utils",
            "mkdir -p /mnt/efs",
            f"mount -t efs -o tls {file_system.file_system_id}:/ /mnt/efs"
        )

        #  5. Create an IAM role for the EC2 instance
        instance_role = iam.Role(self, "InstanceSSMRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")
            ]
        )
        # 6. EC2 instances in private subnets
        for i in range(2):
            instance = ec2.Instance(self, f"Instance{i+1}",
                vpc=vpc,
                vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
                instance_type=ec2.InstanceType("t3.micro"),
                machine_image=ec2.MachineImage.latest_amazon_linux2(),
                security_group=ec2_sg,
                user_data=user_data,
                role=instance_role
            )
            Tags.of(instance).add("Name", f"{project}-{environment}-ec2-{i+1}")

        # Allow EC2 SG to connect to EFS
        file_system.connections.allow_default_port_from(ec2_sg)
