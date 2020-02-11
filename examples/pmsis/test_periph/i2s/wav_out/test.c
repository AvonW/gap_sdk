/*
 * Copyright (C) 2018 GreenWaves Technologies
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/*
 * This example shows how to capture PDM samples and dump them to a WAV file on the workstation.
 */

#include "pmsis.h"
#include "wav_out.h"
#include <bsp/bsp.h>

#define NB_ELEM (8192*8*3)
//#define NB_ELEM (1024 * 16 * 16)
#define BUFF_SIZE (NB_ELEM*2)

static uint8_t pingpong_buffers[2][1024 * 16] = {0};
static uint8_t buff[BUFF_SIZE];
static struct pi_device i2s;

static volatile uint8_t done = 0;

static void __pi_i2s_end_of_rx(void *arg)
{
    printf("I2S transfer completed !\n");
    done = 1;
}

static int test_entry()
{
    printf("Entering main controller\n");

    pi_bsp_init();

    pi_freq_set(PI_FREQ_DOMAIN_FC, 250000000);
    printf("Freq = %ld\n", pi_freq_get(PI_FREQ_DOMAIN_FC));

    // Get default I2S interface config
    struct pi_i2s_conf i2s_conf;
    pi_i2s_conf_init(&i2s_conf);

    // Configure first interface for PDM 44100KHz DDR
    // Also gives the 2 buffers for double-buffering the sampling
    #if 0
    i2s_conf.pingpong_buffers[0] = buff[0];
    i2s_conf.pingpong_buffers[1] = buff[1];
    i2s_conf.block_size = BUFF_SIZE;
    #else
    i2s_conf.pingpong_buffers[0] = pingpong_buffers[0];
    i2s_conf.pingpong_buffers[1] = pingpong_buffers[1];
    i2s_conf.block_size = 1024 * 16;
    #endif
    i2s_conf.frame_clk_freq = 44100;
    //i2s_conf.frame_clk_freq = 48000;
    i2s_conf.itf = 0;
    i2s_conf.channels = 2;
    i2s_conf.format = PI_I2S_FMT_DATA_FORMAT_PDM;
    i2s_conf.word_size = 16;

    pi_open_from_conf(&i2s, &i2s_conf);

    // Open the driver
    if (pi_i2s_open(&i2s))
      return -1;

    // Start sampling, the driver will use the double-buffers we provided to store
    // the incoming samples
    if (pi_i2s_ioctl(&i2s, PI_I2S_IOCTL_START, NULL))
      return -1;

    short *chunk;
    unsigned int size;

    // Capture a few samples
    printf("Capturing data...\n");
    pi_time_wait_us(1000);
    #if 0
    for (int i=0; i<3; i++)
    {
        // Once it returns, chunk will point to the next available buffer
        // containing samples.
        pi_i2s_read(&i2s, (void **)&chunk, &size);
    }
    #else
    pi_task_t task = {0};
    pi_task_callback(&task, __pi_i2s_end_of_rx, NULL);
    //printf("Capturing\n");
    pi_i2s_read_async2(&i2s, buff, BUFF_SIZE, &task);
    while (!done)
    {
        pi_yield();
    }
    chunk = (int16_t *) &buff[0];
    #endif  /* 0 */

    // Now stop sampling
    pi_i2s_ioctl(&i2s, PI_I2S_IOCTL_STOP, NULL);
    printf("Close i2s\n");

    // Close the driver
    pi_i2s_close(&i2s);

    // And display a few samples
    // In DDR mode, the 2 channels are interleaved one by one in the same buffer
    printf("Interface %d / channel 0\n", i2s_conf.itf);
    for (int i=0; i<16; i++)
    {
      printf("  Sample %x: %d\n", i, chunk[i*2]);
    }
    printf("Interface %d / channel 1\n", i2s_conf.itf);
    for (int i=0; i<16; i++)
    {
      printf("  Sample %x: %d\n", i, chunk[i*2+1]);
    }

    dump_wav("out_file.wav", i2s_conf.word_size, i2s_conf.frame_clk_freq,
             i2s_conf.channels, (void *)chunk, BUFF_SIZE);
    return 0;
}

void test_kickoff(void *arg)
{
    int ret = test_entry();
    pmsis_exit(ret);
}

int main()
{
    return pmsis_kickoff((void *)test_kickoff);
}