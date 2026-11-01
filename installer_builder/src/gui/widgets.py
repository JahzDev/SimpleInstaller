"""Reusable parameter input widget."""

from PySide6.QtWidgets import QFormLayout, QLineEdit, QWidget

from ..config.installer_schema import Parameter


class ParameterForm(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.form = QFormLayout(self)
        self.inputs: dict[str, QLineEdit] = {}

    def set_parameters(self, parameters: tuple[Parameter, ...]):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.inputs.clear()
        for parameter in parameters:
            field = QLineEdit()
            field.setPlaceholderText(parameter.description)
            self.form.addRow(f"{parameter.description} ({parameter.name})", field)
            self.inputs[parameter.name] = field

    def values(self) -> dict[str, str]:
        return {name: field.text() for name, field in self.inputs.items()}
