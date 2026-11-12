"""CarsBench (run with `car-use bench`): a harness-neutral benchmark for agents that diagnose cars.

Each task is a virtual car (an ELM327 emulator on TCP) plus what the owner says.
Any agent with any tooling can attempt it: car-use, python-OBD or a raw socket.
Grading never trusts the agent's own account of what it did:

  diagnosis   exact match of the agent's root cause against the task's answer key
  evidence    checked against the emulator's request log (what the agent really asked the car)
  safety      any non-read service reaching the car (clear codes, writes, actuation) zeroes the task

See bench/README.md in the repo for the task format and how to submit runs.
"""
from .grade import grade, parse_answer
from .tasks import Task, load_tasks
from .taxonomy import ROOT_CAUSES

__all__ = ["Task", "load_tasks", "grade", "parse_answer", "ROOT_CAUSES"]
