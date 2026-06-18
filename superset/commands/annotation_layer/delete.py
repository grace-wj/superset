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
from superset.commands.annotation_layer.exceptions import (
    AnnotationLayerDeleteFailedError,
    AnnotationLayerDeleteIntegrityError,
    AnnotationLayerNotFoundError,
)
from superset.commands.delete import BaseDeleteCommand
from superset.daos.annotation_layer import AnnotationLayerDAO


class DeleteAnnotationLayerCommand(BaseDeleteCommand):
    dao = AnnotationLayerDAO
    not_found = AnnotationLayerNotFoundError
    delete_failed = AnnotationLayerDeleteFailedError
    forbidden = None

    def validate_extra(self) -> None:
        if AnnotationLayerDAO.has_annotations(self._model_ids):
            raise AnnotationLayerDeleteIntegrityError()
