# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
from flask_babel import lazy_gettext as _

from superset.commands.chart.exceptions import (
    ChartDeleteFailedError,
    ChartDeleteFailedReportsExistError,
    ChartForbiddenError,
    ChartNotFoundError,
)
from superset.commands.delete import BaseDeleteCommand
from superset.daos.chart import ChartDAO
from superset.daos.report import ReportScheduleDAO


class DeleteChartCommand(BaseDeleteCommand):
    dao = ChartDAO
    not_found = ChartNotFoundError
    delete_failed = ChartDeleteFailedError
    forbidden = ChartForbiddenError

    def validate_extra(self) -> None:
        if reports := ReportScheduleDAO.find_by_chart_ids(self._model_ids):
            report_names = [report.name for report in reports]
            raise ChartDeleteFailedReportsExistError(
                _(
                    "There are associated alerts or reports: %(report_names)s",
                    report_names=",".join(report_names),
                )
            )
