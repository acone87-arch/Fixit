import uuid

import pytest
from pydantic import ValidationError

from app.schemas.equipment import EquipmentCreate, EquipmentInventoryComplete, EquipmentUpdate


@pytest.mark.parametrize('schema,required', [
    (EquipmentCreate, {'equipment_type_id': 1, 'site_id': uuid.uuid4()}),
    (EquipmentInventoryComplete, {'equipment_type_id': 1, 'expected_version': 1}),
    (EquipmentUpdate, {}),
])
def test_optional_serial_normalization(schema, required):
    assert schema(**required).serial_number is None
    for value in [None, '', '   ']:
        assert schema(**required, serial_number=value).serial_number is None
    assert schema(**required, serial_number=' SN-123 ').serial_number == 'SN-123'
    with pytest.raises(ValidationError):
        schema(**required, serial_number='x' * 256)


def test_omitted_serial_patch_preserves_existing_value():
    assert 'serial_number' not in EquipmentUpdate().model_dump(exclude_unset=True)
    assert EquipmentUpdate(serial_number='').model_dump(exclude_unset=True) == {'serial_number': None}
