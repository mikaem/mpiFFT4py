import pytest
import string
import numpy as np
from numpy.random import random, randn
from numpy import allclose, empty, zeros, zeros_like, pi, array, int, all, float64
from numpy.fft import fftfreq
from mpi4py import MPI

from mpiFFT4py.pencil import R2C as Pencil_R2C
from mpiFFT4py.slab import R2C as Slab_R2C
from mpiFFT4py.line import R2C as Line_R2C
from mpiFFT4py import rfft2, rfftn, irfftn, irfft2, fftn, ifftn, irfft, ifft
from mpiFFT4py.slab import C2C

def reset_profile(prof):
    prof.code_map = {}
    prof.last_time = {}
    prof.enable_count = 0
    for func in prof.functions:
        prof.add_function(func)

N = 2**5
L = array([2*pi, 2*pi, 2*pi])
ks = (fftfreq(N)*N).astype(int)
comm = MPI.COMM_WORLD

if comm.Get_size() >= 4:
    params = ("slabas", "slabad", "slabws", "slabwd",
              "pencilsys", "pencilsyd", "pencilnys", "pencilnyd",
              "pencilsxd", "pencilsxs", "pencilnxd", "pencilnxs",
              "pencilaxd", "pencilaxs", "pencilayd", "pencilays")

else:
    params = ("slabas", "slabad", "slabws", "slabwd")

@pytest.fixture(params=params, scope='module')

def FFT(request):
    prec = {"s": "single", "d":"double"}[request.param[-1]]
    if request.param[:3] == "pen":
        communication = {"s": "Alltoall", "n": "AlltoallN", "a": "Alltoallw"}[request.param[-3]]
        alignment = request.param[-2].upper()
        return Pencil_R2C(array([N, 2*N, 4*N]), L, comm, prec, communication=communication, alignment=alignment)
    else:
        communication = 'Alltoall' if request.param[-2] == 'a' else 'Alltoallw'
        return Slab_R2C(array([N, 2*N, 4*N]), L, comm, prec, communication=communication)

@pytest.fixture(params=("lines", "lined"), scope='module')
def FFT2(request):
    prec = {"s": "single", "d":"double"}[request.param[-1]]
    return Line_R2C(array([N, 2*N]), L[:-1], comm, prec)


@pytest.fixture(params=("slabd", "slabs"), scope='module')
def FFT_C2C(request):
    prec = {"s": "single", "d":"double"}[request.param[-1]]
    return C2C(array([N, 2*N, 4*N]), L, comm, prec)

#@profile
def test_FFT(FFT):
    N = FFT.N
    if FFT.rank == 0:
        A = random(N).astype(FFT.float)
        if FFT.communication == 'AlltoallN':
            C = empty(FFT.global_complex_shape(), dtype=FFT.complex)
            C = rfftn(A, C, axes=(0,1,2))
            C[:, :, -1] = 0  # Remove Nyquist frequency
            A = irfftn(C, A, axes=(0,1,2))
        B2 = zeros(FFT.global_complex_shape(), dtype=FFT.complex)
        B2 = rfftn(A, B2, axes=(0,1,2))

    else:
        A = zeros(N, dtype=FFT.float)
        B2 = zeros(FFT.global_complex_shape(), dtype=FFT.complex)

    atol, rtol = (1e-10, 1e-8) if FFT.float is float64 else (5e-7, 1e-4)
    FFT.comm.Bcast(A, root=0)
    FFT.comm.Bcast(B2, root=0)

    a = zeros(FFT.real_shape(), dtype=FFT.float)
    c = zeros(FFT.complex_shape(), dtype=FFT.complex)
    a[:] = A[FFT.real_local_slice()]
    c = FFT.fftn(a, c)
    #print abs((c - B2[FFT.complex_local_slice()])/c.max()).max()
    assert all(abs((c - B2[FFT.complex_local_slice()])/c.max()) < rtol)
    #assert allclose(c, B2[FFT.complex_local_slice()], rtol, atol)
    a = FFT.ifftn(c, a)
    #print abs((a - A[FFT.real_local_slice()])/a.max()).max()

    assert all(abs((a - A[FFT.real_local_slice()])/a.max()) < rtol)
    #assert allclose(a, A[FFT.real_local_slice()], rtol, atol)

def test_FFT2(FFT2):
    N = FFT2.N
    if FFT2.rank == 0:
        A = random(N).astype(FFT2.float)

    else:
        A = zeros(N, dtype=FFT2.float)

    atol, rtol = (1e-10, 1e-8) if FFT2.float is float64 else (5e-7, 1e-4)
    FFT2.comm.Bcast(A, root=0)
    a = zeros(FFT2.real_shape(), dtype=FFT2.float)
    c = zeros(FFT2.complex_shape(), dtype=FFT2.complex)
    a[:] = A[FFT2.real_local_slice()]
    c = FFT2.fft2(a, c)
    B2 = zeros(FFT2.global_complex_shape(), dtype=FFT2.complex)
    B2 = rfft2(A, B2, axes=(0,1))
    assert allclose(c, B2[FFT2.complex_local_slice()], rtol, atol)
    a = FFT2.ifft2(c, a)
    assert allclose(a, A[FFT2.real_local_slice()], rtol, atol)

def test_FFT2_padded(FFT2):
    FFT = FFT2
    N = FFT.N
    prec = "single" if isinstance(FFT.float, np.float32) else "double"
    FFT_SELF = Line_R2C(N, FFT.L, MPI.COMM_SELF, prec)

    if FFT.rank == 0:
        A = random(N).astype(FFT.float)
        C = zeros((FFT.global_complex_shape()), dtype=FFT.complex)
        C = FFT_SELF.fft2(A, C)

        # Eliminate Nyquist, otherwise test will fail
        C[-N[0]//2] = 0

        A_pad = np.zeros(FFT_SELF.real_shape_padded(), dtype=FFT.float)
        A_pad = FFT_SELF.ifft2(C, A_pad, dealias="3/2-rule")

    else:
        C = zeros(FFT.global_complex_shape(), dtype=FFT.complex)
        A_pad = zeros(FFT_SELF.real_shape_padded(), dtype=FFT.float)

    FFT.comm.Bcast(C, root=0)
    FFT.comm.Bcast(A_pad, root=0)

    ae = zeros(FFT.real_shape_padded(), dtype=FFT.float)
    c = zeros(FFT.complex_shape(), dtype=FFT.complex)

    c[:] = C[FFT.complex_local_slice()]
    ae[:] = A_pad[FFT.real_local_slice(padsize=1.5)]

    ap = zeros(FFT.real_shape_padded(), dtype=FFT.float)
    cp = zeros(FFT.complex_shape(), dtype=FFT.complex)
    ap = FFT.ifft2(c, ap, dealias="3/2-rule")

    atol, rtol = (1e-10, 1e-8) if FFT.float is float64 else (5e-7, 1e-4)

    #from IPython import embed; embed()
    #print np.linalg.norm(ap-ae)
    assert allclose(ap, ae, rtol, atol)

    cp = FFT.fft2(ap, cp, dealias="3/2-rule")

    #print np.linalg.norm(abs((cp-c)/cp.max()))
    assert all(abs((cp-c)/cp.max()) < rtol)


def test_FFT_padded(FFT):
    N = FFT.N
    prec = "single" if isinstance(FFT.float, np.float32) else "double"
    FFT_SELF = Slab_R2C(FFT.N, L, MPI.COMM_SELF, prec,
                        communication=FFT.communication)

    if FFT.rank == 0:
        A = random(N).astype(FFT.float)
        C = zeros((FFT.global_complex_shape()), dtype=FFT.complex)
        C = FFT_SELF.fftn(A, C)

        # Eliminate Nyquist, otherwise test will fail
        #C[-N[0]//2] = 0
        #C[:, -N[1]//2] = 0
        if FFT.communication == 'AlltoallN':
            C[:, :, -1] = 0  # Remove Nyquist frequency

        A_pad = np.zeros(FFT_SELF.real_shape_padded(), dtype=FFT.float)
        A_pad = FFT_SELF.ifftn(C, A_pad, dealias='3/2-rule')

    else:
        C = zeros(FFT.global_complex_shape(), dtype=FFT.complex)
        A_pad = zeros(FFT_SELF.real_shape_padded(), dtype=FFT.float)

    FFT.comm.Bcast(C, root=0)
    FFT.comm.Bcast(A_pad, root=0)

    ae = zeros(FFT.real_shape_padded(), dtype=FFT.float)
    c = zeros(FFT.complex_shape(), dtype=FFT.complex)

    c[:] = C[FFT.complex_local_slice()]
    ae[:] = A_pad[FFT.real_local_slice(padsize=1.5)]

    ap = zeros(FFT.real_shape_padded(), dtype=FFT.float)
    cp = zeros(FFT.complex_shape(), dtype=FFT.complex)
    ap = FFT.ifftn(c, ap, dealias="3/2-rule")

    atol, rtol = (1e-10, 1e-8) if FFT.float is float64 else (5e-7, 1e-4)

    #print np.linalg.norm(ap-ae)
    assert allclose(ap, ae, rtol, atol)

    cp = FFT.fftn(ap, cp, dealias="3/2-rule")

    #from IPython import embed; embed()
    #print np.linalg.norm(abs((cp-c)/cp.max()))
    assert all(abs((cp-c)/cp.max()) < rtol)

    #aa = zeros(FFT.real_shape(), dtype=FFT.float)
    #aa = FFT.ifftn(cp, aa)

    #a3 = A[FFT.real_local_slice()]
    #assert allclose(aa, a3, rtol, atol)

def test_FFT_C2C(FFT_C2C):
    """Test both padded and unpadded transforms"""
    FFT = FFT_C2C
    N = FFT.N
    atol, rtol = (1e-8, 1e-8) if FFT.float is float64 else (5e-7, 1e-4)

    if FFT.rank == 0:
        # Create a reference solution using only one CPU
        A = (random(N)+random(N)*1j).astype(FFT.complex)
        C = zeros((FFT.global_shape()), dtype=FFT.complex)
        C = fftn(A, C, axes=(0,1,2))

        # Copy to array padded with zeros
        Cp = zeros((3*N[0]//2, 3*N[1]//2, 3*N[2]//2), dtype=FFT.complex)
        ks = (fftfreq(N[2])*N[2]).astype(int)
        Cp[:N[0]//2, :N[1]//2, ks] = C[:N[0]//2, :N[1]//2]
        Cp[:N[0]//2, -N[1]//2:, ks] = C[:N[0]//2, N[1]//2:]
        Cp[-N[0]//2:, :N[1]//2, ks] = C[N[0]//2:, :N[1]//2]
        Cp[-N[0]//2:, -N[1]//2:, ks] = C[N[0]//2:, N[1]//2:]

        # Get transform of padded array
        Ap = zeros((3*N[0]//2, 3*N[1]//2, 3*N[2]//2), dtype=FFT.complex)
        Ap = ifftn(Cp*1.5**3, Ap, axes=(0,1,2))

    else:
        C = zeros(FFT.global_shape(), dtype=FFT.complex)
        Ap = zeros((3*N[0]//2, 3*N[1]//2, 3*N[2]//2), dtype=FFT.complex)
        A = zeros(N, dtype=FFT.complex)

    # For testing broadcast the arrays computed on root to all CPUs
    FFT.comm.Bcast(C, root=0)
    FFT.comm.Bcast(Ap, root=0)
    FFT.comm.Bcast(A, root=0)

    # Get the single processor solution on local part of the solution
    ae = zeros(FFT.original_shape_padded(), dtype=FFT.complex)
    ae[:] = Ap[FFT.original_local_slice(padsize=1.5)]
    c = zeros(FFT.transformed_shape(), dtype=FFT.complex)
    c[:] = C[FFT.transformed_local_slice()]

    # Perform padded transform with MPI and assert ok
    ap = zeros(FFT.original_shape_padded(), dtype=FFT.complex)
    ap = FFT.ifftn(c, ap, dealias="3/2-rule")
    assert allclose(ap, ae, rtol, atol)

    # Perform truncated transform with MPI and assert
    cp = zeros(FFT.transformed_shape(), dtype=FFT.complex)
    cp = FFT.fftn(ap, cp, dealias="3/2-rule")
    assert all(abs(cp-c)/cp.max() < rtol)

    # Now without padding
    # Transform back to original
    aa = zeros(FFT.original_shape(), dtype=FFT.complex)
    aa = FFT.ifftn(c, aa)
    # Verify
    a3 = A[FFT.original_local_slice()]
    assert allclose(aa, a3, rtol, atol)
    c2 = zeros(FFT.transformed_shape(), dtype=FFT.complex)
    c2 = FFT.fftn(aa, c2)
    # Verify
    assert all(abs(c2-c)/c2.max() < rtol)
    #assert allclose(c2, c, rtol, atol)

#import time
#t0 = time.time()
#test_FFT_padded(Pencil_R2C(array([N, N, N], dtype=int), L, MPI.COMM_WORLD, "double", alignment="Y", communication='Alltoall'))
#t1 = time.time()
#test_FFT_padded(Pencil_R2C(array([N, N, N], dtype=int), L, MPI, "double", alignment="X", communication='Alltoall'))
#t2 = time.time()

#ty = MPI.COMM_WORLD.reduce(t1-t0, op=MPI.MIN)
#tx = MPI.COMM_WORLD.reduce(t2-t1, op=MPI.MIN)
#if MPI.COMM_WORLD.Get_rank() == 0:
    #print "Y: ", ty
    #print "X: ", tx

#test_FFT(Slab_R2C(array([N, 2*N, 4*N]), L, MPI.COMM_WORLD, "double", communication='Alltoall'))
#test_FFT(Pencil_R2C(array([N, N, N], dtype=int), L, MPI.COMM_WORLD, "double", alignment="Y", communication='Alltoall'))
#test_FFT2(Line_R2C(array([N, N]), L[:-1], MPI, "single"))
#test_FFT2_padded(Line_R2C(array([N, N]), L[:-1], MPI, "double"))
#from collections import defaultdict
#FFT = Slab_R2C(array([N//4, N, N]), L, MPI.COMM_WORLD, "double", communication='Alltoallw', threads=2, planner_effort=defaultdict(lambda: "FFTW_MEASURE"))
#test_FFT_padded(FFT)
#reset_profile(profile)
#test_FFT_padded(FFT)

#test_FFT_padded(Pencil_R2C(array([N, N, N], dtype=int), L, MPI, "double", alignment="X", communication='AlltoallN'))
#test_FFT_C2C(C2C(array([N, N, N]), L, MPI, "double"))
