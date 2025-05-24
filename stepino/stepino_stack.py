
from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_autoscaling as autoscaling,
    aws_elasticloadbalancingv2 as elbv2,
    aws_efs as efs,
    Tags,
    RemovalPolicy,
)
from constructs import Construct

class StepinoStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, *, project: str, environment: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Helper for tagging
        def tag_resource(resource, resource_type):
            tag_key = f"{project}-{environment}-{resource_type}"
            Tags.of(resource).add(tag_key, "true")

        # 1. Create VPC with public and private subnets
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
                      ],
                      nat_gateways=1
        )
        tag_resource(vpc, "vpc")

        # 2. Create EFS FileSystem in private subnets
        file_system = efs.FileSystem(self, "EfsFileSystem",
                                     vpc=vpc,
                                     removal_policy=RemovalPolicy.DESTROY,
                                     vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
                                     lifecycle_policy=efs.LifecyclePolicy.AFTER_14_DAYS,  # Optional: lifecycle policy
                                     performance_mode=efs.PerformanceMode.GENERAL_PURPOSE,
                                     )
        tag_resource(file_system, "efs")

        # 3. Security group for ALB
        alb_sg = ec2.SecurityGroup(self, "AlbSG",
                                   vpc=vpc,
                                   allow_all_outbound=True,
                                   description="Security group for ALB"
        )
        alb_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80), "Allow HTTP inbound")
        tag_resource(alb_sg, "alb-sg")

        # 4. Security group for EC2 instances
        ec2_sg = ec2.SecurityGroup(self, "Ec2SG",
                                   vpc=vpc,
                                   allow_all_outbound=True,
                                   description="Security group for EC2 instances"
        )
        # Allow inbound HTTP from ALB only
        ec2_sg.add_ingress_rule(alb_sg, ec2.Port.tcp(80), "Allow HTTP from ALB")
        tag_resource(ec2_sg, "ec2-sg")

        # 5. Security group for EFS
        efs_sg = ec2.SecurityGroup(self, "EfsSG",
                                   vpc=vpc,
                                   allow_all_outbound=True,
                                   description="Security group for EFS"
        )
        # Allow EC2 instances to connect on NFS port 2049
        efs_sg.add_ingress_rule(ec2_sg, ec2.Port.tcp(2049), "Allow NFS from EC2 instances")
        tag_resource(efs_sg, "efs-sg")

        # Attach EFS security group to file system mount targets
        file_system.connections.allow_default_port_from(ec2_sg)

        # 6. Create Application Load Balancer (ALB)
        alb = elbv2.ApplicationLoadBalancer(self, "ALB",
                                            vpc=vpc,
                                            internet_facing=True,
                                            security_group=alb_sg,
                                            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC)
        )
        tag_resource(alb, "alb")

        listener = alb.add_listener("Listener", port=80, open=True)

        # 7. User data script for EC2 instances (install nginx, mount EFS)
        user_data = ec2.UserData.for_linux()
        user_data.add_commands(
            "yum update -y",
            "amazon-linux-extras install -y nginx1",
            "yum install -y amazon-efs-utils",
            "mkdir -p /mnt/efs",
            f"mount -t efs {file_system.file_system_id}:/ /mnt/efs",
            "systemctl enable nginx",
            "systemctl start nginx",
            "cat > /usr/share/nginx/html/index.html <<'EOF'",
            "<!DOCTYPE html>",
            "<html lang=\"en\">",
            "<head>",
            "  <meta charset=\"UTF-8\">",
            "  <title>Fab CDK deployment</title>",
            "  <style>",
            "    body { background: #000; color: #fff; font-family: 'San-serif', Arial, Helvetica, sans-serif; margin: 0; padding: 2em; min-height: 100vh; }",
            "    h1 { margin-top: 0; font-size: 2em; }",
            "    ul { list-style: disc inside; margin: 1em 0 0 0; padding: 0; }",
            "    li { margin-bottom: 0.5em; }",
            "  </style>",
            "</head>",
            "<body>",
            "  <h1>Fab CDK deployment</h1>",
            "  <ul>",
            "    <li>Nginx webserver</li>",
            "    <li>Private instances</li>",
            "    <li>Public ALB</li>",
            "    <li>ASG Target</li>",
            "  </ul>",
            "</body>",
            "</html>",
            "EOF"
        )

        # 8. Create Auto Scaling Group (ASG) for EC2 instances
        asg = autoscaling.AutoScalingGroup(self, "ASG",
                                           vpc=vpc,
                                           instance_type=ec2.InstanceType("t3.nano"),
                                        #    machine_image=ec2.MachineImage.latest_amazon_linux(),
                                           machine_image=ec2.MachineImage.latest_amazon_linux2(), 
                                           min_capacity=1,
                                           max_capacity=2,
                                           associate_public_ip_address=False,
                                           vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
                                           security_group=ec2_sg,
                                           user_data=user_data
        )
        tag_resource(asg, "asg")

        # 9. Attach ASG to ALB target group
        listener.add_targets("TargetGroup",
                             port=80,
                             targets=[asg],
                             health_check=elbv2.HealthCheck(path="/")
        )
