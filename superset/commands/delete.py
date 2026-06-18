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
from __future__ import annotations

import logging
from functools import partial
from typing import Optional

from flask_appbuilder import Model

from superset import security_manager
from superset.commands.base import BaseCommand
from superset.commands.exceptions import (
    CommandException,
    DeleteFailedError,
    ForbiddenError,
)
from superset.daos.base import BaseDAO
from superset.exceptions import SupersetSecurityException
from superset.utils.decorators import on_error, transaction

logger = logging.getLogger(__name__)


class BaseDeleteCommand(BaseCommand):
    """
    Shared base class for bulk-delete commands.

    Subclasses configure class-level attributes and optionally override
    ``validate_extra`` for domain-specific checks (e.g. report-schedule
    associations, integrity constraints).

    Attributes:
        dao: DAO class used for lookup and deletion.
        not_found: Exception class raised when models are missing.
        delete_failed: Exception class used as the ``@transaction`` reraise target.
        forbidden: Exception class raised on ownership failures.
            Set to ``None`` to skip the ownership check.
    """

    dao: type[BaseDAO[Model]] = BaseDAO
    not_found: type[CommandException] = CommandException
    delete_failed: type[CommandException] = DeleteFailedError
    forbidden: Optional[type[CommandException]] = ForbiddenError

    def __init__(self, model_ids: list[int]) -> None:
        self._model_ids = model_ids
        self._models: list[Model] = []

    @transaction(on_error=partial(on_error, reraise=DeleteFailedError))
    def run(self) -> None:
        self.validate()
        self.dao.delete(self._models)

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Rebind the @transaction decorator so `reraise` uses the subclass's
        # delete_failed attribute instead of the base class's default.
        if "run" not in cls.__dict__:

            @transaction(on_error=partial(on_error, reraise=cls.delete_failed))
            def _run(self: BaseDeleteCommand) -> None:
                self.validate()
                self.dao.delete(self._models)

            cls.run = _run  # type: ignore[method-assign]

    def validate(self) -> None:
        self._models = self.dao.find_by_ids(self._model_ids)
        if not self._models or len(self._models) != len(self._model_ids):
            raise self.not_found()

        self.validate_extra()

        if self.forbidden is not None:
            for model in self._models:
                try:
                    security_manager.raise_for_ownership(model)
                except SupersetSecurityException as ex:
                    raise self.forbidden() from ex

    def validate_extra(self) -> None:
        """Override in subclasses to add domain-specific validation."""
