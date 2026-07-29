from abc import ABC, abstractmethod


class QuantumBackend(ABC):
    name: str
    max_qubits: int

    @abstractmethod
    def execute(self, qasm: str, shots: int) -> dict:
        """Run a circuit given as OpenQASM 2 source, return measurement counts."""
