#!/bin/bash
# Regenerates the Python 3 parser. The ANTLR 4.7.2 tool jar comes from the local Maven repository (~/.m2);
# the Python runtime must be antlr4-python3-runtime==4.7.2.
JAR=~/.m2/repository/org/antlr/antlr4/4.7.2/antlr4-4.7.2-complete.jar
java -Xmx500M -cp "$JAR" org.antlr.v4.Tool -Dlanguage=Python3 -visitor -listener Template.g4
touch __init__.py
