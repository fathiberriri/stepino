#!/usr/bin/env python3

import aws_cdk as cdk

from stepino.stepino_stack import StepinoStack


app = cdk.App()
StepinoStack(app, "StepinoStack")

app.synth()
