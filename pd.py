## Copyright (C) 2022 Jun Wako <wakojun@gmail.com>
##
## Permission is hereby granted, free of charge, to any person obtaining a copy
## of this software and associated documentation files (the "Software"), to deal
## in the Software without restriction, including without limitation the rights
## to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
## copies of the Software, and to permit persons to whom the Software is
## furnished to do so, subject to the following conditions:
##
## The above copyright notice and this permission notice shall be included in all
## copies or substantial portions of the Software.
##
## THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
## IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
## FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
## AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
## LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
## OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
## SOFTWARE.

import sigrokdecode as srd

class Decoder(srd.Decoder):
    # https://sigrok.org/wiki/Protocol_decoder_API#Decoder_registration
    api_version = 3
    id = 'adb'
    name = 'ADB'
    longname = 'Apple Desktop Bus'
    desc = 'Decode command and data of Apple Desktop Bus protocol.'
    license = 'mit'
    inputs = ['logic']
    outputs = []
    channels = (
        {'id': 'data', 'name': 'Data', 'desc': 'Data line'},
    )
    options = ()
    tags = ['PC']
    annotations = (
        ('lo', 'Low'),                  # 0
        ('hi', 'High'),                 # 1
        ('attn', 'Attention'),          # 2
        ('reset', 'Global Reset'),      # 3
        ('bit', 'Bit'),                 # 4
        ('byte', 'Byte'),               # 5
        ('start','Start'),              # 6
        ('stop','Stop'),                # 7
        ('srq','Service Request'),      # 8
    )
    annotation_rows = (
        ('cells', 'Cells', (0,1,2,3,8)),
        ('bits', 'Bits', (4,6,7)),
        ('bytes', 'Bytes', (5,)),
    )

    def __init__(self):
        self.reset()

    def reset(self):
        low = 0

    def start(self):
        self.out_ann = self.register(srd.OUTPUT_ANN)

    def metadata(self, key, value):
        if key == srd.SRD_CONF_SAMPLERATE:
            self.samplerate = value

    def to_us(self, sample):
        return (sample / (self.samplerate / 1000000))

    def putl(self, ss, es):
        self.put(ss, es, self.out_ann, [0, ['%d' % self.to_us(es - ss)]])

    def puth(self, ss, es):
        self.put(ss, es, self.out_ann, [1, ['%d' % self.to_us(es - ss)]])

    def puta(self, ss, es):
        self.put(ss, es, self.out_ann, [2, ['Attn:%d' % self.to_us(es - ss), 'Attn', 'A']])

    def putr(self, ss, es):
        self.put(ss, es, self.out_ann, [3, ['Reset:%d' % self.to_us(es - ss), 'RST', 'R']])

    def putb(self, ss, es, b):
        self.put(ss, es, self.out_ann, [4, ['%d' % b]])

    def putB(self, ss, es, B):
        self.put(ss, es, self.out_ann, [5, ['%02X' % B]])

    def putS(self, ss, es):
        self.put(ss, es, self.out_ann, [6, ['Start(1)', 'S1', 'S']])

    def putT(self, ss, es):
        self.put(ss, es, self.out_ann, [7, ['Stop(0)', 'T0', 'T']])

    def putq(self, ss, es):
        self.put(ss, es, self.out_ann, [8, ['SRQ:%d' % self.to_us(es - ss), 'SRQ', 'Q']])

    def decode(self):
        '''
        Bit cell
        --------
                      ___
            bit1: |__|   |
                       __
            bit0: |___|  |
                  \   \  `--- cell_e
                   \   +----- low_e
                    +-------- cell_s

        '''
        byte = 0
        bit_count = 0
        self.wait({0: 'f'})
        cell_s = self.samplenum
        while True:
            # low
            self.wait({0: 'r'})
            low_e = self.samplenum
            len = self.to_us(low_e - cell_s)
            if len < 100:
                # cell-low
                self.putl(cell_s, low_e)

                if bit_count % 8 == 0:
                    byte_s = cell_s
            elif len > 1500:
                # global reset
                self.putr(cell_s, low_e)
            else:
                # 100 <= len < 1500
                if bit_count == 8:
                    # SRQ
                    self.putq(cell_s, low_e)
                else:
                    # attention
                    self.puta(cell_s, low_e)
                bit_count = -1
                byte = 0

            # high
            self.wait({0: 'f'})
            cell_e = self.samplenum

            if self.to_us(cell_e - low_e) < 100:
                # cell-high
                self.puth(low_e, cell_e)

                if self.to_us(cell_e - cell_s) <= 130:
                    # bit-cell  0:___-- 1:__---
                    bit_count += 1
                    if (low_e - cell_s) > (cell_e - low_e):
                        # bit0
                        self.putb(cell_s, cell_e, 0)
                        byte = ((byte << 1) & 0xff) | 0
                    else:
                        # bit 1
                        self.putb(cell_s, cell_e, 1)
                        byte = ((byte << 1) & 0xff) | 1

                    if bit_count == 0:
                        # start-bit(1) __---
                        self.putS(cell_s, cell_e)
                    elif bit_count % 8 == 0:
                        # byte
                        self.putB(byte_s, cell_e, byte)
                else:
                    if self.to_us(low_e - cell_s) < 100:
                        # stop-bit(0)  ___--
                        self.putT(cell_s, cell_e)
                    else:
                        # start-bit(1) after attention  _____---
                        self.putS(low_e, cell_e)
                        bit_count = 0
            else:
                if self.to_us(low_e - cell_s) < 100:
                    # ___-----
                    # stop-bit(0)
                    self.putT(cell_s, low_e)
                #else:
                    # _____-----
                    # attention/SRQ

                bit_count = -1
                byte = 0

            cell_s = cell_e
