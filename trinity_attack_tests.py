import unittest
import time

class Command:
    def __init__(self, args):
        pass

class MockGameImageProcessor:
    def __init__(self, se_value):
        self.se_value = se_value
    
    def find_hayato_se(self):
        return self.se_value

    def decrease_se(self, amount):
        self.se_value -= amount

class MockSkill:
    def __init__(self, decrease_amount=0, processor=None):
        self.activated = False
        self.decrease_amount = decrease_amount
        self.processor = processor
    
    def main(self):
        self.activated = True
        if self.processor and self.decrease_amount:
            self.processor.decrease_se(self.decrease_amount)

class Trinity_Attack(Command):
    def __init__(self, wait: float = 0.5):
        super().__init__(locals())
        self.wait = float(wait)
        self.processor = MockGameImageProcessor(se_value=1000)
        self.PhantomBlade = MockSkill(decrease_amount=400, processor=self.processor)
        self.FalconHonor = MockSkill()
        self.InstanceSlice = MockSkill()
        self.last_falcon_honor_time = time.perf_counter() - 8
        self.last_instance_slice_time = time.perf_counter() - 10

    def main(self):
        now = time.perf_counter()
        hayato_SE = self.processor.find_hayato_se()
        print(f"Current SE: {hayato_SE}")

        if hayato_SE >= 800:
            self.PhantomBlade.main()
            print(f"PhantomBlade activated at SE: {hayato_SE}")
            print(f"SE after PhantomBlade: {self.processor.find_hayato_se()}")
        else:
            if now - self.last_falcon_honor_time > 8:
                self.FalconHonor.main()
            elif now - self.last_instance_slice_time > 10:
                self.InstanceSlice.main()
            else:
                self.PhantomBlade.main()

        time.sleep(self.wait)

class TestTrinityAttack(unittest.TestCase):
    def setUp(self):
        self.attack = Trinity_Attack(wait=0.1)
        # 确保有足够的初始SE
        self.attack.processor = MockGameImageProcessor(se_value=1000)  
        self.attack.PhantomBlade = MockSkill(decrease_amount=400, processor=self.attack.processor)
        self.attack.FalconHonor = MockSkill(decrease_amount=-200, processor=None)  # 假设不减SE
        self.attack.InstanceSlice = MockSkill(decrease_amount=0, processor=None)  # 假设不减SE

    def test_continuous_usage(self):
        print("\nInitial SE:", self.attack.processor.find_hayato_se())
        for i in range(10):
            self.attack.main()
            current_se = self.attack.processor.find_hayato_se()
            activated_skills = []
            if self.attack.PhantomBlade.activated:
                activated_skills.append('PhantomBlade')
            if self.attack.FalconHonor.activated:
                activated_skills.append('FalconHonor')
            if self.attack.InstanceSlice.activated:
                activated_skills.append('InstanceSlice')

            # Reset skill activation status for next iteration
            self.attack.PhantomBlade.activated = False
            self.attack.FalconHonor.activated = False
            self.attack.InstanceSlice.activated = False

            print(f"After iteration {i+1}: SE = {current_se}, Skills activated = {activated_skills}")

if __name__ == '__main__':
    unittest.main()
