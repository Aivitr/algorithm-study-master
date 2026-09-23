/**
 * AudioWorklet 处理器 —— 在独立线程中完成 PCM 降采样 + 格式转换
 * 替代 ScriptProcessor，不再阻塞主线程（UI不卡顿）
 */
class PCMProcessor extends AudioWorkletProcessor {
    constructor(options) {
        super();
        this.srcRate = options.processorOptions.sampleRate || 48000;
        this.targetRate = 16000;
        this.ratio = this.srcRate / this.targetRate;
        // 累积缓冲区（与旧 ScriptProcessor bufferSize=16384 对齐）
        this.bufSize = 16384;
        this.buf = new Float32Array(this.bufSize);
        this.idx = 0;
    }

    process(inputs) {
        const ch = inputs[0] && inputs[0][0];
        if (!ch) return true;

        for (let i = 0; i < ch.length; i++) {
            this.buf[this.idx++] = ch[i];

            if (this.idx >= this.bufSize) {
                // 降采样 + Float32 → Int16
                const outLen = Math.round(this.bufSize / this.ratio);
                const pcm = new Int16Array(outLen);
                for (let j = 0; j < outLen; j++) {
                    const si = Math.floor(j * this.ratio);
                    if (si >= this.bufSize) break;
                    const s = Math.max(-1, Math.min(1, this.buf[si]));
                    pcm[j] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                }
                // 发回主线程（transferable，零拷贝）
                this.port.postMessage(pcm.buffer, [pcm.buffer]);
                this.idx = 0;
            }
        }
        return true;
    }
}

registerProcessor('pcm-processor', PCMProcessor);
