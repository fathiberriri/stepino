#!/usr/bin/env python3

import aws_cdk as cdk

from stepino.stepino_stack import StepinoStack
from stepino.simple_efs_stack import SimpleEfsStack


app = cdk.App()

# Instantiate the first stack
StepinoStack(app, "StepinoStack",
              project="stepino",
              environment="lab")

# Instantiate the second stack
SimpleEfsStack(app, "SimpleEfsStack",
    project="stepino",
    environment="lab"
)              

app.synth()
