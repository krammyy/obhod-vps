# OBHOD Android

Клиент Android на базе sing-box for Android (SFA). Поддерживает импорт и редактирование профилей, переключение профилей и подключение через системный VPN Android.

## Сборка

Установите JDK 17, Android SDK 37.1, Android NDK 28.0.13004108 и Git LFS. После клонирования выполните из корня:

```powershell
git lfs pull
.\gradlew.bat :app:assembleOtherDebug
```

Сборка `otherDebug` использует `app/libs/libbox.aar` из Git LFS. Для варианта `otherLegacy` понадобится отдельный `app/libs/libbox-legacy.aar`. APK обычной отладочной сборки лежит в `app/build/outputs/apk/other/debug/`.

## Подключение

Импортируйте свой профиль в приложении и разрешите создание VPN-подключения. В `app/src/main/assets/obhod/` лежат примеры профилей с условными адресами. Для release-сборки задайте собственную конфигурацию подписи.

## Лицензия и исходный проект

Условия лицензии приведены в [LICENSE](LICENSE). Клиент основан на SFA. Ссылку на документацию исходного проекта см. ниже.

[Документация SFA](https://sing-box.sagernet.org/installation/clients/sfa/)

```
Copyright (C) 2022 by nekohasekai <contact-sagernet@sekai.icu>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <http://www.gnu.org/licenses/>.

In addition, no derivative work may use the name or imply association
with this application without prior consent.
```

Under the license, that forks of the app are not allowed to be listed on F-Droid or other app stores
under the original name.

