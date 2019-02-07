import unittest
import torch
from padertorch.contrib.je.conv1d import TCN


class TestTCN(unittest.TestCase):
    def test_output_shapes(self):
        batch_size = 100
        n_frames = 128

        input_size = 40
        condition_size = 39
        latent_dim = 16

        x = torch.ones(batch_size, input_size, n_frames)
        h = torch.ones(batch_size, condition_size, n_frames)
        for n_scales in [None, 1, 2]:
            for pool_size in [1, 2]:
                for padding in ['both', None]:
                    enc = TCN.from_config(
                        TCN.get_config(
                            updates=dict(
                                input_size=input_size, hidden_sizes=256,
                                output_size=latent_dim,
                                condition_size=condition_size,
                                n_scales=n_scales, norm='batch',
                                pool_sizes=pool_size, padding=padding
                            )
                        )
                    )
                    z, pool_indices = enc(x, h)
                    # self.assertEquals(z.shape, (batch_size, latent_dim, n_frames))
                    dec = TCN.from_config(
                        TCN.get_config(
                            updates=dict(
                                input_size=latent_dim, hidden_sizes=256,
                                output_size=input_size,
                                condition_size=condition_size, transpose=True,
                                n_scales=n_scales, norm='batch',
                                pool_sizes=pool_size, padding=padding
                            )
                        )
                    )
                    x_hat = dec(z, h, pool_indices=pool_indices[::-1])
                    self.assertEquals(x_hat.shape, (batch_size, input_size, n_frames))
