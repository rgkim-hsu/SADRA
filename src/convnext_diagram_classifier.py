"""
ConvNeXt 기반 다이어그램 이미지 분류 모델
- 다이어그램(시스템개념도, 시스템구성도) vs 일반이미지(기타) 분류
- 전이 학습과 데이터 증강을 활용한 고성능 모델
"""

import os
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import torchvision.transforms as transforms
from torchvision.models import convnext_base, ConvNeXt_Base_Weights
import numpy as np
from PIL import Image
import matplotlib.pyplot as plt
from sklearn.metrics import classification_report, confusion_matrix
import seaborn as sns
from tqdm import tqdm
import json
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

class DiagramDataset(Dataset):
    """다이어그램 분류를 위한 커스텀 데이터셋"""
    
    def __init__(self, root_dir, transform=None, split='train'):
        self.root_dir = root_dir
        self.transform = transform
        self.split = split
        
        # 클래스 정의: 0=다이어그램, 1=일반이미지
        self.classes = ['diagram', 'general']
        self.class_to_idx = {'diagram': 0, 'general': 1}
        
        # 데이터 경로 수집
        self.samples = []
        self._load_samples()
        
        print(f"{split} 데이터셋 로드 완료: {len(self.samples)}개 샘플")
        print(f"다이어그램: {sum(1 for _, label in self.samples if label == 0)}개")
        print(f"일반이미지: {sum(1 for _, label in self.samples if label == 1)}개")
    
    def _load_samples(self):
        """데이터셋 경로에서 샘플 수집"""
        # 다이어그램 폴더들 (시스템개념도, 시스템구성도)
        diagram_folders = ['1_시스템개념도', '2_시스템구성도']
        general_folder = '3_기타'
        
        # 다이어그램 이미지 수집
        for folder in diagram_folders:
            folder_path = os.path.join(self.root_dir, folder)
            if os.path.exists(folder_path):
                for filename in os.listdir(folder_path):
                    if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                        img_path = os.path.join(folder_path, filename)
                        self.samples.append((img_path, 0))  # 다이어그램 = 0
        
        # 일반 이미지 수집
        general_path = os.path.join(self.root_dir, general_folder)
        if os.path.exists(general_path):
            for filename in os.listdir(general_path):
                if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                    img_path = os.path.join(general_path, filename)
                    self.samples.append((img_path, 1))  # 일반이미지 = 1
        
        # 데이터셋 분할 (80% 훈련, 20% 검증)
        np.random.seed(42)
        indices = np.random.permutation(len(self.samples))
        
        if self.split == 'train':
            split_idx = int(0.8 * len(self.samples))
            self.samples = [self.samples[i] for i in indices[:split_idx]]
        else:  # validation
            split_idx = int(0.8 * len(self.samples))
            self.samples = [self.samples[i] for i in indices[split_idx:]]
    
    def __len__(self):
        return len(self.samples)
    
    def __getitem__(self, idx):
        img_path, label = self.samples[idx]
        
        try:
            # 이미지 로드
            image = Image.open(img_path).convert('RGB')
            
            if self.transform:
                image = self.transform(image)
            
            return image, label
        except Exception as e:
            print(f"이미지 로드 오류: {img_path}, {e}")
            # 오류 시 빈 이미지 반환
            if self.transform:
                return self.transform(Image.new('RGB', (224, 224), (0, 0, 0))), label
            return Image.new('RGB', (224, 224), (0, 0, 0)), label

class ConvNeXtDiagramClassifier:
    """ConvNeXt 기반 다이어그램 분류기"""
    
    def __init__(self, num_classes=2, device=None):
        self.num_classes = num_classes
        self.device = device if device else torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.model = None
        self.criterion = None
        self.optimizer = None
        self.scheduler = None
        
        print(f"사용 디바이스: {self.device}")
        
    def build_model(self, pretrained=True, freeze_backbone=False):
        """ConvNeXt 모델 구축"""
        print("ConvNeXt 모델 구축 중...")
        
        # 사전 훈련된 ConvNeXt-Base 모델 로드
        if pretrained:
            weights = ConvNeXt_Base_Weights.IMAGENET1K_V1
            self.model = convnext_base(weights=weights)
            print("사전 훈련된 ConvNeXt-Base 모델 로드 완료")
        else:
            self.model = convnext_base(weights=None)
            print("ConvNeXt-Base 모델 (사전 훈련 없음) 로드 완료")
        
        # 분류기 교체
        num_features = self.model.classifier[2].in_features
        self.model.classifier[2] = nn.Linear(num_features, self.num_classes)
        
        # 백본 고정 옵션
        if freeze_backbone:
            for param in self.model.parameters():
                param.requires_grad = False
            # 분류기만 학습 가능하도록 설정
            for param in self.model.classifier.parameters():
                param.requires_grad = True
            print("백본 고정, 분류기만 학습")
        else:
            print("전체 모델 학습")
        
        self.model = self.model.to(self.device)
        
        # 손실 함수 및 옵티마이저 설정
        self.criterion = nn.CrossEntropyLoss()
        self.optimizer = optim.AdamW(
            filter(lambda p: p.requires_grad, self.model.parameters()),
            lr=1e-4,
            weight_decay=0.01
        )
        
        # 학습률 스케줄러
        self.scheduler = optim.lr_scheduler.CosineAnnealingLR(
            self.optimizer, T_max=50, eta_min=1e-6
        )
        
        print(f"모델 파라미터 수: {sum(p.numel() for p in self.model.parameters() if p.requires_grad):,}")
    
    def get_data_transforms(self):
        """데이터 증강 및 전처리 변환 정의"""
        # 훈련용 변환 (데이터 증강 포함)
        train_transform = transforms.Compose([
            transforms.Resize((256, 256)),
            transforms.RandomResizedCrop(224, scale=(0.8, 1.0)),
            transforms.RandomHorizontalFlip(p=0.5),
            transforms.RandomRotation(degrees=10),
            transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2, hue=0.1),
            transforms.RandomAffine(degrees=0, translate=(0.1, 0.1)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])
        
        # 검증용 변환 (증강 없음)
        val_transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])
        
        return train_transform, val_transform
    
    def train_epoch(self, train_loader):
        """한 에포크 훈련"""
        self.model.train()
        running_loss = 0.0
        correct = 0
        total = 0
        
        pbar = tqdm(train_loader, desc="훈련 중")
        for batch_idx, (data, target) in enumerate(pbar):
            data, target = data.to(self.device), target.to(self.device)
            
            self.optimizer.zero_grad()
            output = self.model(data)
            loss = self.criterion(output, target)
            loss.backward()
            self.optimizer.step()
            
            running_loss += loss.item()
            _, predicted = output.max(1)
            total += target.size(0)
            correct += predicted.eq(target).sum().item()
            
            # 진행률 표시
            pbar.set_postfix({
                'Loss': f'{running_loss/(batch_idx+1):.4f}',
                'Acc': f'{100.*correct/total:.2f}%'
            })
        
        epoch_loss = running_loss / len(train_loader)
        epoch_acc = 100. * correct / total
        
        return epoch_loss, epoch_acc
    
    def validate_epoch(self, val_loader):
        """한 에포크 검증"""
        self.model.eval()
        running_loss = 0.0
        correct = 0
        total = 0
        all_preds = []
        all_targets = []
        
        with torch.no_grad():
            pbar = tqdm(val_loader, desc="검증 중")
            for data, target in pbar:
                data, target = data.to(self.device), target.to(self.device)
                output = self.model(data)
                loss = self.criterion(output, target)
                
                running_loss += loss.item()
                _, predicted = output.max(1)
                total += target.size(0)
                correct += predicted.eq(target).sum().item()
                
                all_preds.extend(predicted.cpu().numpy())
                all_targets.extend(target.cpu().numpy())
                
                pbar.set_postfix({
                    'Loss': f'{running_loss/(len(all_preds)/len(val_loader)):.4f}',
                    'Acc': f'{100.*correct/total:.2f}%'
                })
        
        epoch_loss = running_loss / len(val_loader)
        epoch_acc = 100. * correct / total
        
        return epoch_loss, epoch_acc, all_preds, all_targets
    
    def train(self, train_loader, val_loader, epochs=50, save_path='models'):
        """모델 훈련"""
        print(f"\n모델 훈련 시작 - {epochs} 에포크")
        
        # 저장 디렉토리 생성
        os.makedirs(save_path, exist_ok=True)
        
        # 훈련 기록
        train_losses = []
        train_accs = []
        val_losses = []
        val_accs = []
        best_val_acc = 0.0
        
        for epoch in range(epochs):
            print(f"\n에포크 {epoch+1}/{epochs}")
            print("-" * 50)
            
            # 훈련
            train_loss, train_acc = self.train_epoch(train_loader)
            
            # 검증
            val_loss, val_acc, val_preds, val_targets = self.validate_epoch(val_loader)
            
            # 학습률 스케줄링
            self.scheduler.step()
            
            # 기록 저장
            train_losses.append(train_loss)
            train_accs.append(train_acc)
            val_losses.append(val_loss)
            val_accs.append(val_acc)
            
            print(f"훈련 - Loss: {train_loss:.4f}, Acc: {train_acc:.2f}%")
            print(f"검증 - Loss: {val_loss:.4f}, Acc: {val_acc:.2f}%")
            print(f"현재 학습률: {self.optimizer.param_groups[0]['lr']:.6f}")
            
            # 최고 성능 모델 저장
            if val_acc > best_val_acc:
                best_val_acc = val_acc
                torch.save({
                    'epoch': epoch,
                    'model_state_dict': self.model.state_dict(),
                    'optimizer_state_dict': self.optimizer.state_dict(),
                    'val_acc': val_acc,
                    'val_loss': val_loss,
                }, os.path.join(save_path, 'convnext_best.pth'))
                print(f"새로운 최고 성능! 검증 정확도: {val_acc:.2f}%")
        
        # 최종 모델 저장
        torch.save({
            'epoch': epochs,
            'model_state_dict': self.model.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'train_losses': train_losses,
            'train_accs': train_accs,
            'val_losses': val_losses,
            'val_accs': val_accs,
        }, os.path.join(save_path, 'convnext_final.pth'))
        
        # 훈련 곡선 시각화
        self.plot_training_curves(train_losses, train_accs, val_losses, val_accs, save_path)
        
        print(f"\n훈련 완료! 최고 검증 정확도: {best_val_acc:.2f}%")
        return train_losses, train_accs, val_losses, val_accs
    
    def plot_training_curves(self, train_losses, train_accs, val_losses, val_accs, save_path):
        """훈련 곡선 시각화"""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 5))
        
        # 손실 곡선
        ax1.plot(train_losses, label='훈련 손실', color='blue')
        ax1.plot(val_losses, label='검증 손실', color='red')
        ax1.set_title('훈련 및 검증 손실')
        ax1.set_xlabel('에포크')
        ax1.set_ylabel('손실')
        ax1.legend()
        ax1.grid(True)
        
        # 정확도 곡선
        ax2.plot(train_accs, label='훈련 정확도', color='blue')
        ax2.plot(val_accs, label='검증 정확도', color='red')
        ax2.set_title('훈련 및 검증 정확도')
        ax2.set_xlabel('에포크')
        ax2.set_ylabel('정확도 (%)')
        ax2.legend()
        ax2.grid(True)
        
        plt.tight_layout()
        plt.savefig(os.path.join(save_path, 'training_curves.png'), dpi=300, bbox_inches='tight')
        plt.show()
    
    def evaluate(self, val_loader, class_names=None):
        """모델 평가"""
        print("\n모델 평가 중...")
        
        self.model.eval()
        all_preds = []
        all_targets = []
        
        with torch.no_grad():
            for data, target in tqdm(val_loader, desc="평가 중"):
                data, target = data.to(self.device), target.to(self.device)
                output = self.model(data)
                _, predicted = output.max(1)
                
                all_preds.extend(predicted.cpu().numpy())
                all_targets.extend(target.cpu().numpy())
        
        # 분류 보고서
        if class_names is None:
            class_names = ['다이어그램', '일반이미지']
        
        print("\n분류 보고서:")
        print(classification_report(all_targets, all_preds, target_names=class_names))
        
        # 혼동 행렬 시각화
        cm = confusion_matrix(all_targets, all_preds)
        plt.figure(figsize=(8, 6))
        sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', 
                   xticklabels=class_names, yticklabels=class_names)
        plt.title('혼동 행렬')
        plt.ylabel('실제')
        plt.xlabel('예측')
        plt.show()
        
        return all_preds, all_targets
    
    def predict_single_image(self, image_path, transform=None):
        """단일 이미지 예측"""
        if transform is None:
            transform = transforms.Compose([
                transforms.Resize((224, 224)),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
            ])
        
        self.model.eval()
        
        # 이미지 로드 및 전처리
        image = Image.open(image_path).convert('RGB')
        image_tensor = transform(image).unsqueeze(0).to(self.device)
        
        # 예측
        with torch.no_grad():
            output = self.model(image_tensor)
            probabilities = torch.softmax(output, dim=1)
            predicted_class = torch.argmax(output, dim=1).item()
            confidence = probabilities[0][predicted_class].item()
        
        class_names = ['다이어그램', '일반이미지']
        
        return {
            'predicted_class': class_names[predicted_class],
            'confidence': confidence,
            'probabilities': {
                '다이어그램': probabilities[0][0].item(),
                '일반이미지': probabilities[0][1].item()
            }
        }

def main():
    """메인 실행 함수"""
    print("ConvNeXt 다이어그램 분류기 시작")
    print("=" * 60)
    
    # 설정
    DATA_DIR = "dataset_path"
    BATCH_SIZE = 32
    EPOCHS = 50
    NUM_WORKERS = 4
    
    # 디바이스 설정
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"사용 디바이스: {device}")
    
    # 분류기 초기화
    classifier = ConvNeXtDiagramClassifier(num_classes=2, device=device)
    
    # 모델 구축
    classifier.build_model(pretrained=True, freeze_backbone=False)
    
    # 데이터 변환
    train_transform, val_transform = classifier.get_data_transforms()
    
    # 데이터셋 생성
    train_dataset = DiagramDataset(DATA_DIR, transform=train_transform, split='train')
    val_dataset = DiagramDataset(DATA_DIR, transform=val_transform, split='validation')
    
    # 데이터 로더 생성
    train_loader = DataLoader(
        train_dataset, batch_size=BATCH_SIZE, shuffle=True, 
        num_workers=NUM_WORKERS, pin_memory=True
    )
    val_loader = DataLoader(
        val_dataset, batch_size=BATCH_SIZE, shuffle=False, 
        num_workers=NUM_WORKERS, pin_memory=True
    )
    
    print(f"훈련 데이터: {len(train_dataset)}개")
    print(f"검증 데이터: {len(val_dataset)}개")
    
    # 모델 훈련
    train_losses, train_accs, val_losses, val_accs = classifier.train(
        train_loader, val_loader, epochs=EPOCHS
    )
    
    # 모델 평가
    classifier.evaluate(val_loader)
    
    print("\n훈련 완료!")
    print("모델이 'models' 폴더에 저장되었습니다.")

if __name__ == "__main__":
    main()
