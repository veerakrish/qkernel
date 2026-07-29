from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator

from .base import QuantumBackend


class AerSimulatorBackend(QuantumBackend):
    def __init__(self, name: str = "aer-local", max_qubits: int = 32):
        self.name = name
        self.max_qubits = max_qubits
        self._sim = AerSimulator()

    def execute(self, qasm: str, shots: int) -> dict:
        circuit = QuantumCircuit.from_qasm_str(qasm)
        compiled = transpile(circuit, self._sim)
        result = self._sim.run(compiled, shots=shots).result()
        return result.get_counts()
