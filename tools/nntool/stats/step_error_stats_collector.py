# Copyright 2019 GreenWaves Technologies, SAS
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import math
from collections import OrderedDict
from typing import Mapping

import numpy as np

from utils.stats_funcs import qsnr
from utils.node_id import NodeId

from execution.execute_graph import execute_qnoq_iterator
from execution.quantization_mode import QuantizationMode

from graph.types import FilterParameters

from .stats_collector import ReductionStatsCollector

LOG = logging.getLogger('nntool.' + __name__)

class StepErrorStatsCollector(ReductionStatsCollector):
    def __init__(self, limit=None):
        super().__init__()
        self._limit = limit

    def _prepare(self, G):
        pass


    def _collect_execution(self, G, tensors, qrecs):
        outputs = []
        fusion_outputs = []
        for step_idx, node, output, details, qoutput, qdetails, fusion_node in\
            execute_qnoq_iterator(G, tensors, qrecs):
            output = [np.copy(out) for out in output]
            qoutput = [np.copy(out) for out in qoutput]

            if fusion_node:
                fusion_outputs.append({
                    "name": "",
                    "step_idx": "{}_{}".format(step_idx, len(fusion_outputs)),
                    "node": fusion_node,
                    "output": output,
                    "details": details,
                    "qoutput": qoutput,
                    "qdetails": qdetails
                })
            else:
                stat = {
                    "name": node.name,
                    "step_idx": str(step_idx),
                    "node": node,
                    "output": output,
                    "details": details,
                    "qoutput": qoutput,
                    "qdetails": qdetails,
                    "fusion_outputs": []
                }
                if len(fusion_outputs) > 0:
                    stat['fusion_outputs'] = fusion_outputs.copy()
                    fusion_outputs.clear()
                outputs.append(stat)
        return outputs

    @staticmethod
    def _collect_one(out):
        fout = out['output']
        qout = out['qoutput']
        error_ = np.abs(fout[0] - qout[0])
        node = out['node']
        qdetails = out['qdetails']
        if qdetails:
            overflow_dot = qdetails['overflow_dot']
            overflow_acc = qdetails['overflow_acc']
        else:
            overflow_dot = overflow_acc = ""

        stat = {
            'name': out['name'],
            'op_name': node.op_name,
            'step': out['step_idx'],
            'av_err': np.mean(error_),
            'max_err': np.max(error_),
            'min_err': np.min(error_),
            'qsnr': qsnr(fout[0], qout[0]),
            'overflow_dot' : overflow_dot,
            'overflow_acc' : overflow_acc,
            'chan_err': []
        }

        dim = node.out_dims[0]
        if dim and dim.is_named and dim.has_key('c'):
            channel_error = []
            dim = node.out_dims[0]
            for i in range(dim.c):
                srange = dim.srange(c=i)
                channel_error.append(np.average(fout[0][srange] - qout[0][srange]))
            stat['chan_err'] = channel_error

        return stat

    def _collect(self, G, input_tensors) -> Mapping[NodeId, Mapping]:
        LOG.debug("gather quantization statistics")
        outputs = self._collect_execution(G,
                                          input_tensors,
                                          G.quantization)
        stats = OrderedDict()
        for out in outputs:
            if out['fusion_outputs']:
                for fout in out['fusion_outputs']:
                    stats[NodeId(out['node'], fout['node'])] =\
                        self._collect_one(fout)
            stats[NodeId(out['node'], None)] = self._collect_one(out)

        return stats

    def _reduce_prepare(self, all_stats):
        stats = all_stats.pop()
        for stat in stats.values():
            stat['min_qsnr'] = stat['qsnr']
            stat['max_qsnr'] = stat['qsnr']
            for field in ['av_err', 'qsnr', 'chan_err']:
                stat[field] = [stat[field]]

        return stats

    def _reduce(self, _, base: Mapping, stat: Mapping):
        for k in ['av_err', 'qsnr', 'chan_err']:
            base[k].append(stat[k])
        for k in ['overflow_dot', 'overflow_acc']:
            base[k] += stat[k]
        for k in [('max_err', 'max_err')]:
            base[k[0]] = max(base[k[0]], abs(stat[k[1]]))
        for k in [('min_err', 'min_err')]:
            base[k[0]] = min(base[k[0]], abs(stat[k[1]]))
        for k in [('max_qsnr', 'qsnr')]:
            base[k[0]] = max(base[k[0]], stat[k[1]])
        for k in [('min_qsnr', 'qsnr')]:
            base[k[0]] = min(base[k[0]], stat[k[1]])

    @staticmethod
    def _max_abs(l):
        res = (0, 0)
        for el in l:
            ael = math.fabs(el)
            if ael > res[0]:
                res = (ael, el)
        return res[1]

    def _reduce_finalize(self, stats: Mapping) -> Mapping:
        for stat in stats.values():
            for field in ['av_err', 'qsnr']:
                stat[field] = sum(stat[field]) / len(stat[field])
            stat['chan_err'] = [sum(i) for i in zip(*stat['chan_err'])]
            stat['max_chan_err'] = self._max_abs(stat['chan_err'])
        return stats
