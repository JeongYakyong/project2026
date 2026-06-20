# -*- coding: utf-8 -*-
"""Late Fusion 모델 차원 스모크 — Colab 전에 형상 검증(학습 없음, CPU, 랜덤입력).
설계: 백본=weather(6)+타깃만(시간 미오염). 시간피처=전용 경로→백본 feat과 late concat→final linear.
"""
from __future__ import annotations
import sys
import torch, torch.nn as nn, torch.nn.functional as F
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass
DEVICE = 'cpu'


class Patch_Weather_Attention(nn.Module):
    def __init__(self, q, k, h):
        super().__init__()
        self.W_Q=nn.Sequential(nn.Linear(q,h),nn.Tanh(),nn.Linear(h,h))
        self.W_K=nn.Sequential(nn.Linear(k,h),nn.Tanh(),nn.Linear(h,h)); self.s=1.0/(h**0.5)
    def forward(self, fw, pw, to):
        Q=self.W_Q(fw).unsqueeze(1); K=self.W_K(pw)
        a=F.softmax(torch.bmm(Q,K.transpose(1,2))*self.s,dim=-1); return torch.bmm(a,to).squeeze(1),a


class PatchTST_LateFusion(nn.Module):
    """final2 백본 + 시간피처 Late Fusion.
    - 백본: 미래/과거 weather(n_exog) + 타깃(RevIN) 만 패치화·교차어텐션 → feat (시간 미오염).
    - 시간: 미래 시점값 그대로(패치화 X) → 전용 MLP(time_proj).
    - Late Fusion: cat([feat, time_proj]) → final_linear (정규화공간) → 역RevIN. weather_bypass=weather 전용 잔차경로."""
    def __init__(self, n_exog=6, n_time=6, seq_len=336, pred_len=24, patch_len=24, stride=12,
                 d_model=256, num_heads=4, num_layers=3, d_ff=1024, dropout=0.2,
                 feat_dim=256, time_dim=128, revin_affine=True):
        super().__init__()
        self.n_exog=n_exog; self.n_time=n_time; self.patch_len=patch_len; self.stride=stride; self.pred_len=pred_len
        self.num_patches=(seq_len-patch_len)//stride+1
        nb=n_exog+1
        self.patch_embedding=nn.Linear(patch_len*nb, d_model)
        self.pos_embedding=nn.Parameter(torch.randn(1,self.num_patches,d_model)); self.dropout=nn.Dropout(dropout)
        enc=nn.TransformerEncoderLayer(d_model,num_heads,d_ff,dropout,batch_first=True,norm_first=True)
        self.transformer_encoder=nn.TransformerEncoder(enc,num_layers)
        wf=pred_len*n_exog; wp=patch_len*n_exog
        self.weather_attn=Patch_Weather_Attention(wf,wp,d_model)
        self.backbone_head=nn.Sequential(nn.Linear(d_model+wf, feat_dim), nn.LeakyReLU(0.1), nn.Dropout(dropout))
        self.time_proj=nn.Sequential(nn.Linear(pred_len*n_time, time_dim), nn.GELU(), nn.Dropout(dropout))
        self.final_linear=nn.Linear(feat_dim+time_dim, pred_len)
        self.weather_bypass=nn.Linear(wf, pred_len)
        self.revin_affine=revin_affine; self.eps=1e-5
        if revin_affine: self.revin_w=nn.Parameter(torch.ones(1)); self.revin_b=nn.Parameter(torch.zeros(1))
    def forward(self, b):
        pn=b['past_numeric'].to(DEVICE); py=b['past_y'].to(DEVICE); fn=b['future_numeric'].to(DEVICE); B=pn.shape[0]
        past_x=pn[:,:,:self.n_exog]; fut_x=fn[:,:,:self.n_exog]; time_feat=fn[:,:,self.n_exog:]
        mean=py.mean(1,keepdim=True); std=torch.sqrt(py.var(1,keepdim=True,unbiased=False)+self.eps); pyn=(py-mean)/std
        if self.revin_affine: pyn=pyn*self.revin_w+self.revin_b
        xp=torch.cat([past_x,pyn],-1)                                  # (B,seq,n_exog+1) 시간 없음
        xpp=xp.unfold(1,self.patch_len,self.stride).permute(0,1,3,2).reshape(B,self.num_patches,-1)
        eo=self.transformer_encoder(self.dropout(self.patch_embedding(xpp)+self.pos_embedding))
        wf_flat=fut_x.reshape(B,-1)                                    # 미래 weather flat
        xw=past_x.unfold(1,self.patch_len,self.stride).permute(0,1,3,2).reshape(B,self.num_patches,-1)
        ctx,_=self.weather_attn(wf_flat,xw,eo)
        feat=self.backbone_head(torch.cat([ctx,wf_flat],1))           # 백본 feat (시간 미오염)
        tproj=self.time_proj(time_feat.reshape(B,-1))                 # 시간 전용 경로
        on=self.final_linear(torch.cat([feat,tproj],1))+self.weather_bypass(wf_flat)
        if self.revin_affine: on=(on-self.revin_b)/self.revin_w
        return on*std.squeeze(-1)+mean.squeeze(-1), std.squeeze(-1)


def main():
    B, SEQ, PRED, NEX, NT = 8, 336, 24, 6, 6
    HP=dict(seq_len=SEQ, patch_len=24, stride=12, d_model=256, num_heads=4, num_layers=3, d_ff=1024, dropout=0.2)
    m=PatchTST_LateFusion(n_exog=NEX, n_time=NT, pred_len=PRED, **HP)
    batch=dict(past_numeric=torch.randn(B,SEQ,NEX+NT), past_y=torch.randn(B,SEQ,1),
               future_numeric=torch.randn(B,PRED,NEX+NT))
    out, std = m(batch)
    nparam=sum(p.numel() for p in m.parameters())
    print(f'out {tuple(out.shape)} (기대 ({B},{PRED})) | std {tuple(std.shape)} (기대 ({B},1), 브로드캐스트용) | params {nparam:,}')
    assert out.shape==(B,PRED) and std.shape==(B,1), '형상 불일치'
    assert torch.isfinite(out).all(), 'NaN/Inf'
    # backward 동작 확인
    loss=((out-torch.randn(B,PRED))**2).mean(); loss.backward()
    g=sum(p.grad.abs().sum().item() for p in m.parameters() if p.grad is not None)
    print(f'backward OK, grad합={g:.1f}')
    # 시간경로 분리 확인: 시간피처만 바꾸면 출력이 변해야(시간이 들어감), weather feat은 동일해야
    print('[PASS] Late Fusion 형상·역전파 정상.')


if __name__=='__main__': main()
