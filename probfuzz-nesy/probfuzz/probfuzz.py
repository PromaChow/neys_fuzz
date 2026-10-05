#!/usr/bin/env python
"""ProbFuzz adapted to neurosymbolic libraries (Python 3 port of uiuc-arc/probfuzz, commit 2914413).

usage: ./probfuzz.py [#programs] [--template NAME|all] [--special] [--seed N]
"""
import argparse
import os
import random
import threading
import queue
import time

import numpy as np

from utils.utils import *
from language.templateparser import TemplatePopulator

_TOOL = 'tool'
_ENABLED = 'enabled'
_ALGORITHM = 'algorithm'
_TIMEOUT = 'timeout'

# choose fuzzer type: structured programs are rejected and regenerated when the checker finds them invalid
set_fuzzer_type('STR')


def make_backend(config, runconfig, file_dir, parts):
    """parts = (data, priors, distmap, constmap, template, config) from the populator."""
    from backends.oracle import Oracle
    from backends.scallop import Scallop
    from backends.deepproblog import DeepProbLog
    from backends.problog import ProbLog
    from backends.neurasp import NeurASP
    cls = {'oracle': Oracle, 'scallop': Scallop, 'deepproblog': DeepProbLog, 'problog': ProbLog,
           'neurasp': NeurASP}[runconfig[_TOOL]]
    return cls(file_dir, *parts, runconfig[_ALGORITHM])


class InferenceEngineRunner(threading.Thread):
    def __init__(self, id, queue, runconfigs, parts_by_prog):
        threading.Thread.__init__(self)
        self.queue = queue
        self.id = id
        self.runconfigs = runconfigs

    def run(self):
        while not self.queue.empty():
            prog_id, backends = self.queue.get(block=False)
            for runconfig, backend in backends:
                print("Running {0} {1} program {2} >>>>".format(runconfig[_TOOL], runconfig[_ALGORITHM], prog_id + 1))
                backend.run(runconfig[_TIMEOUT], prog_id + 1, runconfig['python'])


def filterCommonDistributions(models, runconfigurations):
    """Keep only distributions that every enabled tool can express (ProbFuzz's own filter)."""
    filteredModels = []
    for model in models:
        i = 1
        for config in runconfigurations:
            if config[_ENABLED] and (config[_TOOL] not in model.keys()):
                i = 0
                break
        if i == 1:
            filteredModels.append(model)
    return filteredModels


def generate_programs_from_template(progs, template_name, special, seed):
    config = read_config()
    max_thread = config['max_threads']
    structured = config['structured']
    set_special(special)
    if seed is not None:
        np.random.seed(seed)
        random.seed(seed)

    names = list(config['templates']) if template_name == 'all' else [template_name or config['current_template']]
    dirname = config['output_dir'] + "/progs" + str(time.strftime("%Y%m%d-%H%M%S"))
    queues = [queue.Queue() for _ in range(0, max_thread)]
    all_models = filterCommonDistributions(parse_models(), config['runConfigurations'])

    count = 0
    for name in names:
        current_template = config['templates'][name]
        for i in range(0, progs):
            file_dir_name = dirname + '/' + name + '_' + str(i + 1)
            os.makedirs(file_dir_name, exist_ok=True)
            template_populator = TemplatePopulator(file_dir_name, current_template, all_models)
            data, priors, distmap, constmap = template_populator.populate(structured)
            # check if model is valid if structured check is enabled
            if structured:
                attempts = 0
                while not template_populator.validModel and attempts < 1000:
                    data, priors, distmap, constmap = template_populator.populate()
                    attempts += 1
                if not template_populator.validModel:
                    print("Err: no valid completion of " + name + " found")
                    continue
            backends = []
            for toolconfig in config['runConfigurations']:
                if toolconfig[_ENABLED]:
                    b = make_backend(config, toolconfig, file_dir_name,
                                     (data, priors, distmap, constmap, current_template, config))
                    b.create_program()
                    backends.append((toolconfig, b))
            queues[count % max_thread].put((i, backends))
            count += 1

    print("Output directory : " + dirname)
    threads = []
    for i in range(0, max_thread):
        print("Starting thread .. " + str(i + 1))
        thread = InferenceEngineRunner(i, queues[i], config['runConfigurations'], None)
        thread.start()
        threads.append(thread)
    for i in range(0, max_thread):
        threads[i].join()

    printSummary(dirname, config)


def printSummary(dir, config):
    print("Printing summary")
    from metrics.summary import summarize
    summarize(dir, config)
    print("Summary written in summary.csv")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument('programs', type=int, help='programs to generate per template')
    ap.add_argument('--template', default=None, help="template name from config.json, or 'all'")
    ap.add_argument('--special', action='store_true', help='generate special constants (0, 1, epsilon, float32 limits)')
    ap.add_argument('--seed', type=int, default=None)
    a = ap.parse_args()
    generate_programs_from_template(a.programs, a.template, a.special, a.seed)
